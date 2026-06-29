import os
import json
import base64
from google.oauth2.service_account import Credentials

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID_SNOWFIT = os.environ.get("TELEGRAM_CHAT_ID_SNOWFIT", "-5475683054")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

EU_BEDFRAME_SHEET_ID = os.environ.get(
    "EU_BEDFRAME_SHEET_ID", "1wKSkIsWmxjQQ7gH0NvXqq2lXrGeeMtL9_0O4Pe2E_PE"
)
SHEET_TAB = "Sheet1"

INVOICE_FOLDER_ID = os.environ.get(
    "INVOICE_FOLDER_ID", "1U1RKlFve6MVxIEJMOIjJimB_--xDcqJ9"
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_google_credentials() -> Credentials:
    creds_b64 = os.environ.get("GOOGLE_CREDENTIALS_BASE64")
    if creds_b64:
        creds_json = json.loads(base64.b64decode(creds_b64))
        return Credentials.from_service_account_info(creds_json, scopes=SCOPES)

    creds_json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json_str:
        creds_json = json.loads(creds_json_str)
        return Credentials.from_service_account_info(creds_json, scopes=SCOPES)

    creds_path = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    if os.path.exists(creds_path):
        return Credentials.from_service_account_file(creds_path, scopes=SCOPES)

    raise RuntimeError(
        "No Google credentials found. Set GOOGLE_CREDENTIALS_BASE64, "
        "GOOGLE_CREDENTIALS_JSON, or GOOGLE_CREDENTIALS_FILE."
    )
