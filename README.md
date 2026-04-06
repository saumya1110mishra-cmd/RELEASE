# Release Notes Agent

A Python automation script that:
1. Fetches release notes from Google Ads, Meta Ads, and Google Analytics.
2. Writes them into a Google Sheet.
3. Emails the sheet link weekly (can be cron-scheduled).

## Setup

### 1️⃣ Install dependencies
```bash
pip install -r requirements.txt
```

### 2️⃣ Setup Google APIs
- Create a Google Cloud project.
- Enable Google Sheets API.
- Create a service account and download `credentials.json`.
- Share your Google Sheet with that service account email.

### 3️⃣ Gmail App Password
- Enable 2FA and generate an App Password from: https://myaccount.google.com/apppasswords
- Use that in `release_agent.py`

### 4️⃣ Run Locally
```bash
python release_agent.py
```

### 5️⃣ (Optional) Schedule with Cron
```bash
0 8 * * MON /usr/bin/python3 /path/to/release_agent.py >> /var/log/release_agent.log 2>&1
```
