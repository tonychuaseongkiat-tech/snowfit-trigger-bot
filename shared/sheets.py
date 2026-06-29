import gspread
from shared.config import get_google_credentials


def get_gspread_client() -> gspread.Client:
    creds = get_google_credentials()
    return gspread.authorize(creds)


def open_sheet(sheet_id: str, tab_name: str) -> gspread.Worksheet:
    gc = get_gspread_client()
    spreadsheet = gc.open_by_key(sheet_id)
    return spreadsheet.worksheet(tab_name)


def read_all_rows(sheet_id: str, tab_name: str) -> list[list[str]]:
    ws = open_sheet(sheet_id, tab_name)
    return ws.get_all_values()
