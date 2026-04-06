import os
import feedparser
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from email.mime.text import MIMEText
import smtplib
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
from dotenv import load_dotenv
load_dotenv()
# -------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------
# GOOGLE_SHEET_ID = "10mrWQDc8u0N1wGmYX-671x2Qu7KnwsbZcTv2creXnkY"
# SERVICE_ACCOUNT_FILE = "credentials.json"
# RECIPIENTS = ["saumya1110mishra@gmail.com"]
# SENDER_EMAIL = "saumya1110mishra@gmail.com"
# SENDER_APP_PASSWORD = "kipc xjil fipt tjmz"
# GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_APP_PASSWORD = os.getenv("SENDER_APP_PASSWORD")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RECIPIENTS = os.getenv("RECIPIENTS")
#genai.configure(api_key=GEMINI_API_KEY)
# model = genai.GenerativeModel("gemini-1.5-flash")
# model = genai.GenerativeModel("gemini-1.5-flash-latest")
#model = genai.GenerativeModel("gemini-1.5-pro-latest")
#client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

# def generate_ai_summary(text):
#     try:
#         prompt = f"""
# You are a Marketing Technology Analyst.

# Summarize the following release notes clearly for business users.

# Return ONLY in this format:

# Focus on:
# - Business impact
# - Revenue implications
# - Required actions for marketers
# - Keep it concise and actionable

# Release Notes:
# {text}
# """

#         response = client.chat.completions.create(
#             model="gpt-4o-mini",
#             messages=[
#                 {"role": "user", "content": prompt}
#             ],
#             temperature=0.3
#         )

#         return response.choices[0].message.content.strip()

#     except Exception as e:
#         print("AI Summary Error:", e)
#         return "AI Summary unavailable"


# def generate_ai_summary(text):
#     """
#     Uses Google Gemini (free tier)
#     to create business-friendly release summary
#     """

#     try:
#         prompt = f"""
# You are a Marketing Technology Analyst.

# Summarize the following release notes clearly for business users.

# Return ONLY in this format:

# Impact:
# Action Required:
# Risk Level:
# Who Should Care:

# Release Notes:
# {text}
# """

#         response = model.generate_content(prompt)

#         if response.text:
#             return response.text.strip()

#         return "AI Summary unavailable"

#     except Exception as e:
#         print("AI Summary Error:", e)
#         return "AI Summary unavailable"

## - de-duplication logic
def get_existing_records():
    creds_dict = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))

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
    creds_dict = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))

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
    creds_dict = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))

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
    creds_dict = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))

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
