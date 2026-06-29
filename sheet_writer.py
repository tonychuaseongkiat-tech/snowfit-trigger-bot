import re
import logging
from datetime import date, timedelta
from shared.config import EU_BEDFRAME_SHEET_ID, SHEET_TAB
from shared.sheets import open_sheet

logger = logging.getLogger("sheet-writer")

MONTH_NAMES = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}

COL_B = 2   # SG PI No.
COL_K = 11  # Delivery Mth
COL_N = 14  # Status


def find_pending_divider_row(ws) -> int | None:
    """Find the yellow PENDING divider row by scanning for 'PENDING' text."""
    all_values = ws.get_all_values()
    for i, row in enumerate(all_values, start=1):
        for cell in row:
            if cell.strip().upper() == "PENDING":
                return i
    return None


def parse_existing_delivery_date(raw: str, ref_year: int = None) -> date | None:
    """Parse delivery dates like '5Aug', '15Jul', '3Jul' from preparing section."""
    if not raw or not ref_year:
        ref_year = date.today().year

    match = re.match(r"(\d{1,2})([A-Za-z]+)", raw.strip())
    if not match:
        return None

    day = int(match.group(1))
    month_str = match.group(2).lower()[:3]

    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    month = month_map.get(month_str)
    if not month:
        return None

    try:
        return date(ref_year, month, day)
    except ValueError:
        return None


def parse_existing_month_year(raw: str) -> tuple[int, int] | None:
    """Parse month/year like '10/2026', '08/2026' from pending section."""
    match = re.match(r"(\d{1,2})/(\d{4})", raw.strip())
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def write_order(parsed_caption: dict, extracted: dict) -> dict:
    """
    Write order data to the correct section of Sheet1.

    Returns dict with status, row number, and section.
    """
    ws = open_sheet(EU_BEDFRAME_SHEET_ID, SHEET_TAB)
    pending_row = find_pending_divider_row(ws)

    if not pending_row:
        return {"status": "error", "reason": "Could not find PENDING divider row"}

    is_pending = parsed_caption["is_pending"]

    row_data = build_row_data(parsed_caption, extracted)

    if is_pending:
        insert_row = find_pending_insert_position(ws, pending_row, parsed_caption)
    else:
        insert_row = find_preparing_insert_position(ws, pending_row, parsed_caption)

    ws.insert_row(row_data, insert_row, value_input_option="USER_ENTERED")

    section = "Pending" if is_pending else "Preparing"
    delivery_display = parsed_caption["delivery_raw"]
    logger.info("Wrote %s to %s at row %d — Delivery %s",
                parsed_caption["pi_no"], section, insert_row, delivery_display)

    return {
        "status": "ok",
        "row": insert_row,
        "section": section,
        "pi_no": parsed_caption["pi_no"],
        "delivery": delivery_display,
    }


def build_row_data(parsed_caption: dict, extracted: dict) -> list:
    """Build the row data list for columns A through O."""
    is_pending = parsed_caption["is_pending"]

    order_date_str = ""
    deliver_jb_str = ""

    if is_pending:
        month_year = parsed_caption.get("delivery_month_year", "")
        parsed_my = parse_existing_month_year(month_year)
        if parsed_my:
            prev_month = parsed_my[0] - 1
            prev_year = parsed_my[1]
            if prev_month < 1:
                prev_month = 12
                prev_year -= 1
            order_date_str = f"ORDER IN {MONTH_NAMES[prev_month].upper()}"
    elif parsed_caption.get("delivery_date"):
        d = parsed_caption["delivery_date"]
        monday = d - timedelta(days=d.weekday())
        order_monday = monday - timedelta(weeks=3)
        jb_monday = monday - timedelta(weeks=1)
        order_date_str = f"{order_monday.day}/{order_monday.month}"
        deliver_jb_str = f"{jb_monday.day}/{jb_monday.month}"

    status = "Waiting" if is_pending else "Ordered"

    return [
        "",                                          # A - No. (blank)
        parsed_caption["pi_no"],                     # B - SG PI No.
        extracted.get("design", ""),                  # C - Design
        extracted.get("storage", ""),                 # D - Storage
        extracted.get("headboard", ""),               # E - Headboard
        extracted.get("color", ""),                   # F - Color
        extracted.get("size", ""),                    # G - Size
        extracted.get("mattress", ""),                # H - For Mattress
        extracted.get("remark", ""),                  # I - Special Remark
        extracted.get("sales_person", "TONY"),       # J - Sales Person
        parsed_caption["delivery_raw"],              # K - Delivery Mth
        order_date_str,                              # L - Order Date
        deliver_jb_str,                              # M - DELIVER JB
        status,                                      # N - Status
        "",                                          # O - Special Request
    ]


def find_preparing_insert_position(ws, pending_row: int, parsed_caption: dict) -> int:
    """
    Find where to insert in the preparing section (above PENDING divider).
    Sorted by delivery date ascending.
    """
    if not parsed_caption.get("delivery_date"):
        return pending_row

    target_date = parsed_caption["delivery_date"]
    ref_year = target_date.year

    all_values = ws.get_all_values()

    header_row = 1
    first_data_row = header_row + 1

    for row_idx in range(pending_row - 2, first_data_row - 2, -1):
        if row_idx < 0 or row_idx >= len(all_values):
            continue
        row = all_values[row_idx]
        if len(row) < COL_K:
            continue
        cell = row[COL_K - 1].strip()
        if not cell:
            continue
        existing_date = parse_existing_delivery_date(cell, ref_year)
        if existing_date and existing_date <= target_date:
            return row_idx + 2
        if existing_date and existing_date > target_date:
            continue

    return first_data_row


def find_pending_insert_position(ws, pending_row: int, parsed_caption: dict) -> int:
    """
    Find where to insert in the pending section (below PENDING divider).
    Sorted by delivery month/year ascending.
    """
    target_my = parsed_caption.get("delivery_month_year", "")
    target_parsed = parse_existing_month_year(target_my)
    if not target_parsed:
        all_values = ws.get_all_values()
        last_data_row = pending_row + 1
        for i in range(pending_row, len(all_values)):
            row = all_values[i]
            if any(cell.strip() for cell in row):
                last_data_row = i + 2
        return last_data_row

    target_month, target_year = target_parsed

    all_values = ws.get_all_values()

    last_same_or_earlier = pending_row

    for row_idx in range(pending_row, len(all_values)):
        row = all_values[row_idx]
        if len(row) < COL_K:
            continue
        cell = row[COL_K - 1].strip()
        if not cell:
            continue

        existing = parse_existing_month_year(cell)
        if not existing:
            continue

        ex_month, ex_year = existing

        if (ex_year, ex_month) <= (target_year, target_month):
            last_same_or_earlier = row_idx + 1
        else:
            return row_idx + 1

    return last_same_or_earlier + 1
