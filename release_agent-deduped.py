import os
import feedparser
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from email.mime.text import MIMEText
import smtplib
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
import google.generativeai as genai

# -------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------
GOOGLE_SHEET_ID = "10mrWQDc8u0N1wGmYX-671x2Qu7KnwsbZcTv2creXnkY"
SERVICE_ACCOUNT_FILE = "credentials.json"
RECIPIENTS = ["saumya1110mishra@gmail.com"]
SENDER_EMAIL = "saumya1110mishra@gmail.com"
SENDER_APP_PASSWORD = "kipc xjil fipt tjmz"
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

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

import requests
from bs4 import BeautifulSoup


def fetch_latest_release_from_html(url, platform):
    """
    Reads release notes webpage
    Extracts latest version/date
    Builds clean human-readable summary
    """

    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        version = None
        summary = []

        # --------------------------------------------------
        # 1️⃣ VERSION STYLE RELEASES (Google Ads)
        # --------------------------------------------------
        for h in soup.find_all(["h1", "h2", "h3"]):
            text = h.get_text(strip=True)

            version_match = re.search(r'v?\d+(\.\d+)+', text)

            if version_match:
                version = version_match.group(0)

                nxt = h.find_next_sibling()

                while nxt and len(summary) < 8:
                    if nxt.name == "ul":
                        for li in nxt.find_all("li"):
                            summary.append(li.get_text(" ", strip=True))

                    if nxt.name == "p":
                        summary.append(nxt.get_text(" ", strip=True))

                    nxt = nxt.find_next_sibling()

                break

        # --------------------------------------------------
        # 2️⃣ DATE BASED RELEASES (Microsoft + LinkedIn)
        # --------------------------------------------------
        if not version:
            for h in soup.find_all(["h1", "h2", "h3"]):
                text = h.get_text(strip=True)

                if re.search(
                    r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}',
                    text,
                    re.IGNORECASE,
                ):
                    version = text

                    nxt = h.find_next_sibling()

                    while nxt and len(summary) < 8:
                        if nxt.name == "ul":
                            for li in nxt.find_all("li"):
                                summary.append(li.get_text(" ", strip=True))

                        if nxt.name == "p":
                            summary.append(nxt.get_text(" ", strip=True))

                        nxt = nxt.find_next_sibling()

                    break

        # --------------------------------------------------
        # SAFETY CHECK
        # --------------------------------------------------
        if not version or not summary:
            print(f"⚠️ {platform} release not parsed.")
            return None

        # --------------------------------------------------
        # ✨ CLEAN HUMAN-READABLE FORMAT
        # --------------------------------------------------
        cleaned_summary = []

        for s in summary:
            s = re.sub(r'\s+', ' ', s)      # remove extra spaces
            s = s.replace(" .", ".")
            if len(s) > 20:                # ignore tiny junk text
                cleaned_summary.append(s)

        # bullet formatting for Google Sheet readability
        formatted_summary = "\n".join(
            [f"• {line}" for line in cleaned_summary[:6]]
        )

        return {
            "Platform": platform,
            "Version/Release Month": version,
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
    """
    Uses Google Gemini (free tier)
    to create business-friendly release summary
    """

    try:
        prompt = f"""
You are a Marketing Technology Analyst.

Summarize the following release notes clearly for business users.

Return ONLY in this format:

Impact:
Action Required:
Risk Level:
Who Should Care:

Release Notes:
{text}
"""

        response = model.generate_content(prompt)

        if response.text:
            return response.text.strip()

        return "AI Summary unavailable"

    except Exception as e:
        print("AI Summary Error:", e)
        return "AI Summary unavailable"

# -------------------------------------------------------------
# GOOGLE SHEETS WRITER
# -------------------------------------------------------------
def append_to_google_sheet(data):
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()

    # Prepare values for appending
    values = [[d["Platform"], d["Version/Release Month"], d["Summary"], d["Date"]] for d in data]

    # Check if header exists
    existing = sheet.values().get(
        spreadsheetId=GOOGLE_SHEET_ID,
        range="A1:D1"
    ).execute()

    if not existing.get("values"):
        headers = [["Platform", "Version/Release Month", "Release Notes", "Date"]]
        sheet.values().update(
            spreadsheetId=GOOGLE_SHEET_ID,
            range="A1:D1",
            valueInputOption="RAW",
            body={"values": headers}
        ).execute()
        print("🧾 Added header row to sheet.")

    # Append data
    body = {"values": values}
    sheet.values().append(
        spreadsheetId=GOOGLE_SHEET_ID,
        range="A2:D",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body=body
    ).execute()

    print(f"✅ {len(values)} new rows added to Google Sheet.")


# -------------------------------------------------------------
# EMAIL SENDER
# -------------------------------------------------------------
def send_email(sheet_link, recipients):
    subject = "📢 Weekly Release Notes Update"
    body = f"""Hi Team,

Here’s the weekly release notes summary from Google Ads, Meta Ads, and Google Analytics:

🔗 Google Sheet: {sheet_link}

Best,  
Release Agent 🤖
"""

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.starttls()
        smtp.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
        smtp.sendmail(SENDER_EMAIL, recipients, msg.as_string())

    print("📨 Email sent successfully!")


# -------------------------------------------------------------
# MAIN AGENT
# -------------------------------------------------------------
def main():
    print("🔍 Fetching release notes from all sources...")
    all_data = fetch_all_release_notes()

    if not all_data:
        print("⚠️ No release notes found.")
        return

    append_to_google_sheet(all_data)
    sheet_link = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}"
    send_email(sheet_link, RECIPIENTS)
    print("✅ Release Agent completed successfully.")


if __name__ == "__main__":
    main()
