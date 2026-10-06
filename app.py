import math
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
DATABASE_PATH = INSTANCE_DIR / "stock_ledger.sqlite3"
CROPS = ("Managu", "Terere", "Kunde", "Mrenda", "Sukuma wiki", "Other indigenous greens")
PAYMENT_STATUSES = ("Pending", "Paid")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "local-development-key-change-before-deploying")


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def init_db():
    INSTANCE_DIR.mkdir(exist_ok=True)
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_receipts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    farmer_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    county TEXT NOT NULL,
                    crop TEXT NOT NULL,
                    delivered_kg REAL NOT NULL CHECK (delivered_kg > 0),
                    accepted_kg REAL NOT NULL CHECK (accepted_kg >= 0),
                    price_per_kg REAL NOT NULL CHECK (price_per_kg >= 0),
                    payment_status TEXT NOT NULL CHECK (payment_status IN ('Pending', 'Paid')),
                    received_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )


def account_exists():
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        return connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def format_received_at(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%d %b, %H:%M")
    except (TypeError, ValueError):
        return "Time unavailable"


def get_dashboard_data(search=""):
    today = datetime.now().strftime("%Y-%m-%d")
    search = search.strip()
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        today_row = connection.execute(
            """
            SELECT COUNT(*) AS deliveries,
                   COALESCE(SUM(accepted_kg), 0) AS accepted_kg
            FROM stock_receipts
            WHERE date(received_at) = ?
            """,
            (today,),
        ).fetchone()
        outstanding = connection.execute(
            "SELECT COALESCE(SUM(accepted_kg * price_per_kg), 0) FROM stock_receipts WHERE payment_status = 'Pending'"
        ).fetchone()[0]
        crop_totals = connection.execute(
            """
            SELECT crop, SUM(accepted_kg) AS accepted_kg
            FROM stock_receipts
            GROUP BY crop
            ORDER BY accepted_kg DESC, crop
            """
        ).fetchall()

        where = ""
        parameters = []
        if search:
            where = "WHERE farmer_name LIKE ? OR phone LIKE ? OR county LIKE ? OR crop LIKE ?"
            pattern = f"%{search}%"
            parameters = [pattern, pattern, pattern, pattern]
        receipts = connection.execute(
            f"""
            SELECT id, farmer_name, phone, county, crop, delivered_kg, accepted_kg,
                   price_per_kg, payment_status,
                   accepted_kg * price_per_kg AS total_value,
                   CASE
                       WHEN accepted_kg = 0 THEN 'Rejected'
                       WHEN accepted_kg < delivered_kg THEN 'Partial'
                       ELSE 'Accepted'
                   END AS intake_status,
                   received_at
            FROM stock_receipts
            {where}
            ORDER BY received_at DESC, id DESC
            LIMIT 50
            """,
            parameters,
        ).fetchall()
        receipts = [
            {**dict(receipt), "received_label": format_received_at(receipt["received_at"])}
            for receipt in receipts
        ]

    max_accepted = max((row["accepted_kg"] for row in crop_totals), default=0)
    crop_rows = [
        {
            "crop": row["crop"],
            "accepted_kg": row["accepted_kg"],
            "share": round(row["accepted_kg"] / max_accepted * 100) if max_accepted else 0,
        }
        for row in crop_totals
    ]
    return {
        "today_label": datetime.now().strftime("%A, %d %B %Y"),
        "today_deliveries": today_row["deliveries"],
        "today_accepted_kg": today_row["accepted_kg"],
        "outstanding_value": outstanding,
        "crop_rows": crop_rows,
        "receipts": receipts,
        "search": search,
    }


init_db()


@app.get("/")
def home():
    if "username" in session:
        return redirect(url_for("stock_dashboard"))
    if not account_exists():
        return redirect(url_for("register"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "username" in session:
        return redirect(url_for("stock_dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with closing(sqlite3.connect(DATABASE_PATH)) as connection:
            user = connection.execute(
                "SELECT username, password_hash FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
        if user and check_password_hash(user[1], password):
            session.clear()
            session["username"] = user[0]
            return redirect(url_for("stock_dashboard"))
        flash("Login failed. Check your username and password.", "error")

    return render_template("login.html", is_registration=False, registration_open=not account_exists())


@app.route("/register", methods=["GET", "POST"])
def register():
    if "username" in session:
        return redirect(url_for("stock_dashboard"))
    if account_exists():
        flash("An account already exists. Sign in to continue.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password_confirmation = request.form.get("password_confirmation", "")
        if not username or len(username) > 50:
            flash("Enter a username of 1 to 50 characters.", "error")
        elif len(password) < 8:
            flash("Choose a password with at least 8 characters.", "error")
        elif password != password_confirmation:
            flash("The passwords do not match.", "error")
        else:
            password_hash = generate_password_hash(password)
            with closing(sqlite3.connect(DATABASE_PATH)) as connection:
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                        flash("An account already exists. Sign in to continue.", "error")
                        return redirect(url_for("login"))
                    connection.execute(
                        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                        (username, password_hash, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    )
            flash("Account created. Sign in with your new username and password.", "success")
            return redirect(url_for("login"))

    return render_template("login.html", is_registration=True, registration_open=True)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/stock")
@login_required
def stock_dashboard():
    return render_template(
        "stock_dashboard.html",
        crops=CROPS,
        payment_statuses=PAYMENT_STATUSES,
        **get_dashboard_data(request.args.get("q", "")),
    )


@app.post("/stock-intake")
@login_required
def stock_intake():
    farmer_name = request.form.get("farmer_name", "").strip()
    phone = request.form.get("phone", "").strip()
    county = request.form.get("county", "").strip()
    crop = request.form.get("crop", "")
    payment_status = request.form.get("payment_status", "")

    try:
        delivered_kg = float(request.form.get("delivered_kg", ""))
        accepted_kg = float(request.form.get("accepted_kg", ""))
        price_per_kg = float(request.form.get("price_per_kg", ""))
    except ValueError:
        flash("Enter valid numbers for delivered weight, accepted weight, and price.", "error")
        return redirect(url_for("stock_dashboard", _anchor="intake"))

    valid_numbers = all(math.isfinite(value) for value in (delivered_kg, accepted_kg, price_per_kg))
    valid_receipt = (
        all((farmer_name, phone, county))
        and crop in CROPS
        and payment_status in PAYMENT_STATUSES
        and valid_numbers
        and delivered_kg > 0
        and 0 <= accepted_kg <= delivered_kg
        and price_per_kg >= 0
    )
    if not valid_receipt:
        flash("Check the farmer details and make sure accepted kilos do not exceed delivered kilos.", "error")
        return redirect(url_for("stock_dashboard", _anchor="intake"))

    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO stock_receipts (
                    farmer_name, phone, county, crop, delivered_kg, accepted_kg,
                    price_per_kg, payment_status, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    farmer_name,
                    phone,
                    county,
                    crop,
                    delivered_kg,
                    accepted_kg,
                    price_per_kg,
                    payment_status,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            receipt_id = cursor.lastrowid

    flash(f"Receipt #{receipt_id} saved. {accepted_kg:g} kg added to accepted stock.", "success")
    return redirect(url_for("stock_dashboard", _anchor="intake"))


@app.post("/receipt/<int:receipt_id>/payment")
@login_required
def update_payment_status(receipt_id):
    payment_status = request.form.get("payment_status", "")
    if payment_status not in PAYMENT_STATUSES:
        flash("Choose a valid payment status.", "error")
        return redirect(url_for("stock_dashboard", _anchor="history"))

    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        with connection:
            result = connection.execute(
                "UPDATE stock_receipts SET payment_status = ? WHERE id = ?",
                (payment_status, receipt_id),
            )

    if result.rowcount:
        flash(f"Receipt #{receipt_id} marked {payment_status.lower()}.", "success")
    else:
        flash("That receipt could not be found.", "error")
    return redirect(url_for("stock_dashboard", _anchor="history"))


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
