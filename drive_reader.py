import io
import re
import logging
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from shared.config import get_google_credentials, INVOICE_FOLDER_ID

logger = logging.getLogger("drive-reader")


def get_drive_service():
    creds = get_google_credentials()
    return build("drive", "v3", credentials=creds)


def download_invoice_pdf(order_id: str) -> bytes | None:
    """Download invoice PDF from Google Drive by order ID (e.g. SG-0626-0037)."""
    match = re.match(r"SG-(\d{4})-\d{4}", order_id)
    if not match:
        logger.error("Invalid order ID format: %s", order_id)
        return None

    month_code = match.group(1)
    pdf_name = f"{order_id}.pdf"

    try:
        drive = get_drive_service()

        result = drive.files().list(
            q=f"name = '{month_code}' and '{INVOICE_FOLDER_ID}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            fields="files(id)",
            pageSize=1,
        ).execute()
        folders = result.get("files", [])
        if not folders:
            logger.warning("Month folder '%s' not found in Drive", month_code)
            return None

        folder_id = folders[0]["id"]

        result = drive.files().list(
            q=f"name = '{pdf_name}' and '{folder_id}' in parents and mimeType = 'application/pdf' and trashed = false",
            fields="files(id, name)",
            pageSize=1,
        ).execute()
        files = result.get("files", [])
        if not files:
            logger.warning("Invoice PDF '%s' not found in folder '%s'", pdf_name, month_code)
            return None

        file_id = files[0]["id"]
        request = drive.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        logger.info("Downloaded %s (%d bytes)", pdf_name, fh.tell())
        return fh.getvalue()

    except Exception as e:
        logger.error("Failed to download %s: %s", order_id, e)
        return None
