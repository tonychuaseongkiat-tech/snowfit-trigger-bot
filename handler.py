import re
import logging
from datetime import datetime, date

logger = logging.getLogger("handler")

INVOICE_PATTERN = re.compile(r"(?:SG-?)?(\d{4})-(\d{4})(?:\((\d+)\))?", re.IGNORECASE)

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def parse_caption(text: str) -> dict | None:
    """
    Parse /order caption into structured data.

    Expected format (one item per line):
        /order
        SG-0626-0037
        Delivery Oct
        Pending          (optional)

    Returns dict with: invoice_raw, pi_no, delivery_raw, delivery_date,
                       delivery_month_year, is_pending, has_specific_date
    """
    if not text:
        return None

    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]

    if not lines or not lines[0].lower().startswith("/order"):
        return None

    if len(lines) < 3:
        return None

    invoice_line = lines[1]
    match = INVOICE_PATTERN.search(invoice_line)
    if not match:
        return None

    month_code = match.group(1)
    seq_num = match.group(2)
    sub_num = match.group(3)

    if sub_num:
        pi_no = f"PIS-{month_code}<{seq_num}>{sub_num}"
    else:
        pi_no = f"PIS-{month_code}<{seq_num}>"

    invoice_raw = match.group(0)

    delivery_line = lines[2]
    delivery_info = parse_delivery(delivery_line)
    if not delivery_info:
        return None

    is_pending = False
    if len(lines) >= 4:
        for line in lines[3:]:
            if line.lower().strip() == "pending":
                is_pending = True
                break

    return {
        "invoice_raw": invoice_raw,
        "pi_no": pi_no,
        "delivery_raw": delivery_info["raw"],
        "delivery_date": delivery_info.get("date"),
        "delivery_month_year": delivery_info.get("month_year"),
        "has_specific_date": delivery_info["has_specific_date"],
        "is_pending": is_pending,
    }


def parse_delivery(line: str) -> dict | None:
    """
    Parse delivery line like:
        Delivery Oct          → month only (pending)
        Delivery 5th Aug      → specific date (preparing)
        Delivery 15 Jul       → specific date
        Delivery Aug          → month only
    """
    text = line.strip()
    if text.lower().startswith("delivery"):
        text = text[8:].strip()

    if not text:
        return None

    today = date.today()
    current_year = today.year

    day_match = re.match(r"(\d{1,2})(?:st|nd|rd|th)?\s+(\w+)", text, re.IGNORECASE)
    if day_match:
        day = int(day_match.group(1))
        month_str = day_match.group(2).lower()
        month = MONTH_MAP.get(month_str)
        if month:
            year = current_year
            if month < today.month - 1:
                year += 1
            try:
                delivery_date = date(year, month, day)
            except ValueError:
                return None

            raw = f"{day}{day_match.group(2).capitalize()}"
            return {
                "raw": raw,
                "date": delivery_date,
                "month_year": f"{month:02d}/{year}",
                "has_specific_date": True,
            }

    month_str = text.strip().lower()
    month = MONTH_MAP.get(month_str)
    if month:
        year = current_year
        if month < today.month - 1:
            year += 1
        raw = f"{month:02d}/{year}"
        return {
            "raw": raw,
            "month_year": f"{month:02d}/{year}",
            "has_specific_date": False,
        }

    return None


def convert_invoice_to_pi(invoice: str) -> str:
    """Convert SG-0626-0037 to PIS-0626<0037> format."""
    match = INVOICE_PATTERN.search(invoice)
    if not match:
        return invoice
    month_code = match.group(1)
    seq_num = match.group(2)
    sub_num = match.group(3)
    if sub_num:
        return f"PIS-{month_code}<{seq_num}>{sub_num}"
    return f"PIS-{month_code}<{seq_num}>"


def calc_order_date(delivery_date: date) -> date:
    """Monday 3 weeks before delivery date's week Monday."""
    monday_of_week = delivery_date - __import__("datetime").timedelta(days=delivery_date.weekday())
    return monday_of_week - __import__("datetime").timedelta(weeks=3)


def calc_deliver_jb(delivery_date: date) -> date:
    """Monday 1 week before delivery date's week Monday."""
    monday_of_week = delivery_date - __import__("datetime").timedelta(days=delivery_date.weekday())
    return monday_of_week - __import__("datetime").timedelta(weeks=1)


def format_date_short(d: date) -> str:
    """Format date as d/m (e.g. 13/7, 27/7)."""
    return f"{d.day}/{d.month}"
