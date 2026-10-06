# mavuno-circle

A Flask stock-taking desk for recording indigenous vegetables received from farmers.

## Run locally

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SECRET_KEY = "replace-with-a-long-random-secret"
python app.py
```

Open http://127.0.0.1:5000 and choose **Create the first account**. Create a username and password, then sign in. Passwords are stored as secure hashes in `instance/stock_ledger.sqlite3`; registration closes after the first account is created. Stock pages and write actions require an authenticated session.

Each receipt records delivered and accepted weight separately, agreed price per kilogram, and payment status. The dashboard summarizes accepted weight received today, outstanding farmer value, and accepted totals by vegetable.

Before deployment, set a strong `SECRET_KEY` environment variable and configure production hosting for Flask. Create the first account only from a trusted environment because that account can access the full stock ledger.
