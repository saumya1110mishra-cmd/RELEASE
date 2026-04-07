import os
import feedparser
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from email.mime.text import MIMEText
import smtplib
import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime
import json
from dotenv import load_dotenv
load_dotenv()
# -------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_APP_PASSWORD = os.getenv("SENDER_APP_PASSWORD")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RECIPIENTS = os.getenv("RECIPIENTS")


# -------------------------------------------------------------
# RSS FETCHERS
# -------------------------------------------------------------
def parse_feed(url, platform):
    feed = feedparser.parse(url)
    releases = []

    for entry in feed.entries[:5]:  # Fetch latest 5
        title = entry.get("title", "").strip()
        summary = entry.get("summary", "").strip().replace("\n", " ")
        date = entry.get("published", "N/A")
        version = extract_version(title)

        releases.append({
            "Platform": platform,
            "Version/Release Month": version,
            "Summary": title or summary,
            "Date": date
        })
    return releases


def extract_version(text):
    """Try to extract version patterns like v1.2, API v16, etc."""
    import re
    match = re.search(r'v?\d+(\.\d+)*', text)
    return match.group(0) if match else "N/A"

def fetch_with_retry(url):
        for attempt in range(3):
            try:
                response = requests.get(url, timeout=40)
                response.raise_for_status()
                return response
            except Exception as e:
                print(f"Retry {attempt+1} failed: {e}")
        return None

# (only showing the UPDATED FUNCTION — rest of your code remains SAME)

def fetch_latest_release_from_html(url, platform):
    try:
        response = fetch_with_retry(url)
        if not response:
            print(f"❌ Failed to fetch {platform}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        main = soup.find("main") or soup

        version = None
        summary = []

        # ==================================================
        # ✅ GOOGLE ADS
        # ==================================================
        if "google-ads" in url:

            # Find correct version header
            for h in main.find_all("h2"):
                text = h.get_text(strip=True)

                if re.search(r'v\d+(\.\d+)+', text, re.IGNORECASE):
                    version = text
                    target = h
                    break

            started = False

            for elem in target.find_all_next():

                if elem.name == "h2" and elem != target:
                    break

                if elem.name in ["h3", "h4"]:
                    started = True
                    continue

                if not started:
                    continue

                if elem.name == "li":
                    text = elem.get_text(" ", strip=True)

                    if "introduces" in text.lower():
                        continue
                    if "the following new features" in text.lower():
                        continue

                    if len(text) > 30:
                        summary.append(text)

        # ==================================================
        # ✅ MICROSOFT ADS
        # ==================================================
        elif "advertising" in url:

            for h in main.find_all("h2"):
                text = h.get_text(strip=True)

                if re.search(
                    r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}',
                    text,
                    re.IGNORECASE
                ):
                    version = text
                    target = h
                    break

            current_section = None

            for elem in target.find_all_next():

                # stop at next month
                if elem.name == "h2" and elem != target:
                    break

                # capture section title
                if elem.name == "h3":
                    current_section = elem.get_text(strip=True)
                    continue

                # ✅ ONLY take leaf <li> (no nested lists inside)
                if elem.name == "li" and not elem.find("ul"):

                    text = elem.get_text(" ", strip=True)

                    if len(text) < 30:
                        continue
                    if "see below" in text.lower():
                        continue

                    # ✅ IGNORE shorter duplicate-like lines
                    # keep only more detailed ones
                    if ":" in text and text.count(":") > 1:
                        continue

                    if current_section:
                        text = f"{current_section}: {text}"

                    summary.append(text)

        # ==================================================
        # ✅ LINKEDIN ADS
        # ==================================================
        elif "linkedin" in url:

            for h in main.find_all("h2"):
                text = h.get_text(strip=True)

                if "Version" in text:
                    version = text
                    target = h
                    break

            seen = set()

            for elem in target.find_all_next():

                if elem.name == "h2" and elem != target:
                    break

                # ✅ ONLY take bullet points (PRIMARY SOURCE)
                if elem.name == "li":

                    text = elem.get_text(" ", strip=True)

                    if len(text) < 30:
                        continue

                    key = re.sub(r'\W+', '', text.lower())

                    if key in seen:
                        continue

                    seen.add(key)
                    summary.append(text)

                # ✅ take paragraph ONLY if no bullet version exists
                elif elem.name == "p":

                    text = elem.get_text(" ", strip=True)

                    if len(text) < 60:
                        continue

                    key = re.sub(r'\W+', '', text.lower())

                    # skip if similar bullet already exists
                    if any(key in s or s in key for s in seen):
                        continue

                    seen.add(key)
                    summary.append(text)

        # ==================================================
        # ✅ FINAL CLEANUP
        # ==================================================
        if not summary:
            summary = ["Release detected but details not parsed"]

        formatted_summary = "\n".join(
            [f"• {line}" for line in summary[:10]]
        )

        return {
            "Platform": platform,
            "Version/Release Month": version or "Latest",
            "Summary": formatted_summary,
            "Date": datetime.now().strftime("%Y-%m-%d"),
        }

    except Exception as e:
        print(f"❌ Error fetching {platform}: {e}")
        return None
  
def fetch_all_release_notes():
    sources = {
        "Google Ads": "https://developers.google.com/google-ads/api/docs/release-notes",
        "Microsoft Ads": "https://learn.microsoft.com/advertising/guides/release-notes",
        "LinkedIn Ads": "https://learn.microsoft.com/linkedin/marketing/integrations/recent-changes"
    }

    all_data = []

    for platform, url in sources.items():
        print(f"📥 Fetching {platform} releases...")
        latest_release = fetch_latest_release_from_html(url, platform)

        if latest_release:
            all_data.append(latest_release)
        else:
            print(f"⚠️ No release detected for {platform}")

    return all_data

def generate_ai_summary(text):
    try:
        account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        api_token = os.getenv("CLOUDFLARE_API_TOKEN")

        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/meta/llama-3-8b-instruct"

        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

        prompt = f"""
You are a Marketing Technology Analyst.

Summarize the following release notes clearly for business users.

Return ONLY in this format:

Impact:
Action Required:
Risk Level:
Who Should Care:

Do NOT add any extra sentences like "Let me know..." or explanations.

Release Notes:
{text}
"""

        payload = {
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        response = requests.post(url, headers=headers, json=payload)

        if response.status_code != 200:
            print("Cloudflare AI Error:", response.text)
            return "AI Summary unavailable"

        result = response.json()

        return result["result"]["response"].strip()

    except Exception as e:
        print("AI Summary Error:", e)
        return "AI Summary unavailable"

## - de-duplication logic
def get_existing_records():
    service_account_json = os.getenv("SERVICE_ACCOUNT_JSON")

    if service_account_json:
        creds_dict = json.loads(service_account_json)
    else:
        with open("credentials.json") as f:
            creds_dict = json.load(f)

    creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()

    result = sheet.values().get(
        spreadsheetId=GOOGLE_SHEET_ID,
        range="A2:E"
    ).execute()

    rows = result.get("values", [])

    existing = set()

    for row in rows:
        if len(row) >= 3:
            key = (row[0], row[1], row[2])  # Platform, Version, Summary
            existing.add(key)

    return existing


# -------------------------------------------------------------
# GOOGLE SHEETS WRITER
# -------------------------------------------------------------
def append_to_google_sheet(data):
    service_account_json = os.getenv("SERVICE_ACCOUNT_JSON")

    if service_account_json:
        creds_dict = json.loads(service_account_json)
    else:
        with open("credentials.json") as f:
            creds_dict = json.load(f)

    creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()

    # Prepare values for appending
    ##values = [[d["Platform"], d["Version/Release Month"], d["Summary"], d["Date"]] for d in data]
    existing_records = get_existing_records()

    values = []

    for d in data:
        key = (d["Platform"], d["Version/Release Month"], d["Summary"])

        if key in existing_records:
            print(f"⏭️ Skipping duplicate: {d['Platform']} - {d['Version/Release Month']}")
            continue

        ai_summary = generate_ai_summary(d["Summary"])

        values.append([
            d["Platform"],
            d["Version/Release Month"],
            d["Summary"],
            d["Date"],
            ai_summary
        ])

    # Check if header exists
    existing = sheet.values().get(
        spreadsheetId=GOOGLE_SHEET_ID,
        range="A1:E1"
    ).execute()

    if not existing.get("values"):
        headers = [["Platform", "Version/Release Month", "Release Notes", "Date", "AI Summary"]]
        sheet.values().update(
            spreadsheetId=GOOGLE_SHEET_ID,
            range="A1:E1",
            valueInputOption="RAW",
            body={"values": headers}
        ).execute()
        print("🧾 Added header row to sheet.")

    if not values:
        print("✅ No updates available")
        return False
    
    # Append data
    body = {"values": values}
    sheet.values().append(
        spreadsheetId=GOOGLE_SHEET_ID,
        range="A2:E",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body=body
    ).execute()

    print(f"✅ {len(values)} new rows added to Google Sheet.")
    return True


def get_latest_rows(limit=3):
    service_account_json = os.getenv("SERVICE_ACCOUNT_JSON")

    if service_account_json:
        creds_dict = json.loads(service_account_json)
    else:
        with open("credentials.json") as f:
            creds_dict = json.load(f)

    creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()

    result = sheet.values().get(
        spreadsheetId=GOOGLE_SHEET_ID,
        range="A2:E"
    ).execute()

    rows = result.get("values", [])

    # Get latest rows
    return rows[-limit:]

# -------------------------------------------------------------
# EMAIL SENDER
# -------------------------------------------------------------
def send_email(sheet_link, recipients):
    # -------------------------------------------------------------
    # FETCH LATEST ROWS FROM GOOGLE SHEET
    # -------------------------------------------------------------
    service_account_json = os.getenv("SERVICE_ACCOUNT_JSON")

    if service_account_json:
        creds_dict = json.loads(service_account_json)
    else:
        with open("credentials.json") as f:
            creds_dict = json.load(f)

    creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()

    result = sheet.values().get(
        spreadsheetId=GOOGLE_SHEET_ID,
        range="A2:E"
    ).execute()

    rows = result.get("values", [])

    # Get last 3 rows (latest updates)
    latest_rows = rows[-3:] if len(rows) >= 3 else rows

    # -------------------------------------------------------------
    # FORMAT EMAIL CONTENT
    # -------------------------------------------------------------
    formatted_summary = ""

    for row in latest_rows:
        try:
            platform = row[0]
            version = row[1]
            ai_summary = row[4] if len(row) > 4 else "No AI summary available"

            formatted_summary += f"""
🔹 {platform} ({version})

{ai_summary}

------------------------
"""
        except Exception:
            continue

    # -------------------------------------------------------------
    # EMAIL BODY
    # -------------------------------------------------------------
    body = f"""Hi Team,

Here are the latest release updates:

{formatted_summary}

🔗 Full Google Sheet: {sheet_link}

Best,  
Release Agent 🤖
"""

    # -------------------------------------------------------------
    # SEND EMAIL
    # -------------------------------------------------------------
    msg = MIMEText(body)
    msg["Subject"] = "📢 Release Notes Summary (Latest Updates)"
    msg["From"] = SENDER_EMAIL
    msg["To"] = ", ".join(recipients if isinstance(recipients, list) else [recipients])

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.starttls()
        smtp.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
        smtp.sendmail(
            SENDER_EMAIL,
            recipients if isinstance(recipients, list) else [recipients],
            msg.as_string()
        )

    print("📨 Email sent successfully with summaries!")
# -------------------------------------------------------------
# MAIN AGENT
# -------------------------------------------------------------
def main():
    print("🔍 Fetching release notes from all sources...")
    all_data = fetch_all_release_notes()

    if not all_data:
        print("⚠️ No release notes found.")
        return

    updated = append_to_google_sheet(all_data)

    if not updated:
        return  # 🚀 stop here, no email
    sheet_link = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}"
    send_email(sheet_link, RECIPIENTS)
    print("✅ Release Agent completed successfully.")


if __name__ == "__main__":
    main()
