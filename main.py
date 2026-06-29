"""
Snowfit Trigger Bot — Telegram photo-to-sheet automation.

Listens for /order commands with invoice photos in the SNOWFIT EU Order group.
Extracts order details via Gemini Vision AI and writes to Google Sheet.
"""

import os
import logging
import threading
import time
import json
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

from shared.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID_SNOWFIT
from shared.telegram import get_updates, download_file, send_message, send_error_alert
from handler import parse_caption
from vision import extract_order_details
from sheet_writer import write_order

SGT = timezone(timedelta(hours=8))
PORT = int(os.environ.get("PORT", 8080))
POLL_INTERVAL = 2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("snowfit-trigger-bot")


def process_order_message(message: dict):
    """Process a single /order message with photo."""
    chat_id = str(message["chat"]["id"])
    message_id = message["message_id"]
    caption = message.get("caption", "")

    parsed = parse_caption(caption)
    if not parsed:
        send_message(chat_id, "❌ Could not parse caption. Expected format:\n/order\nSG-XXXX-XXXX\nDelivery [date/month]\n[Pending]", message_id)
        return

    logger.info("Processing order: %s (pending=%s)", parsed["pi_no"], parsed["is_pending"])

    photos = message.get("photo", [])
    if not photos:
        send_message(chat_id, "❌ No photo found in message.", message_id)
        return

    largest_photo = max(photos, key=lambda p: p.get("file_size", 0))
    file_id = largest_photo["file_id"]

    photo_bytes = download_file(file_id)
    if not photo_bytes:
        send_message(chat_id, "❌ Failed to download photo.", message_id)
        return

    extracted = extract_order_details(photo_bytes)
    if not extracted:
        send_message(chat_id, "❌ Could not extract order details from photo. Please try with a clearer image.", message_id)
        return

    try:
        result = write_order(parsed, extracted)
    except Exception as e:
        logger.error("Sheet write failed: %s", e, exc_info=True)
        send_message(chat_id, f"❌ Failed to write to sheet: {e}", message_id)
        send_error_alert("snowfit-trigger-bot", "write_order", str(e))
        return

    if result["status"] == "ok":
        section = result["section"]
        row = result["row"]
        pi_no = result["pi_no"]
        delivery = result["delivery"]
        emoji = "📋" if section == "Pending" else "✅"
        send_message(chat_id, f"{emoji} *{pi_no}* added to *{section}* (row {row}) — Delivery {delivery}", message_id)
    else:
        send_message(chat_id, f"❌ Error: {result.get('reason', 'unknown')}", message_id)


def start_polling():
    """Poll Telegram for /order messages with photos."""
    logger.info("Starting Telegram polling...")
    logger.info("Bot token set: %s", bool(TELEGRAM_BOT_TOKEN))
    logger.info("Chat ID: %s", TELEGRAM_CHAT_ID_SNOWFIT)
    offset = 0
    poll_count = 0

    while True:
        try:
            updates = get_updates(offset)
            poll_count += 1
            if updates:
                logger.info("Poll #%d: got %d updates", poll_count, len(updates))
            elif poll_count <= 3:
                logger.info("Poll #%d: no updates", poll_count)

            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message")
                if not message:
                    logger.info("Update %d: no message field", update["update_id"])
                    continue

                caption = message.get("caption", "")
                has_photo = bool(message.get("photo"))
                chat_id = message.get("chat", {}).get("id")
                logger.info("Message from chat %s: photo=%s, caption='%s'", chat_id, has_photo, caption[:50])

                if has_photo and caption.strip().lower().startswith("/order"):
                    try:
                        process_order_message(message)
                    except Exception as e:
                        logger.error("Error processing message: %s", e, exc_info=True)
                        send_error_alert("snowfit-trigger-bot", "process_message", str(e))

        except Exception as e:
            logger.error("Polling error: %s", e, exc_info=True)
            time.sleep(5)

        time.sleep(POLL_INTERVAL)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            now = datetime.now(SGT).isoformat()
            body = json.dumps({
                "status": "ok",
                "service": "snowfit-trigger-bot",
                "time": now,
            })
            self.wfile.write(body.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        logger.debug(format, *args)


def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    poll_thread = threading.Thread(target=start_polling, daemon=True)
    poll_thread.start()
    logger.info("Telegram polling started")

    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info("Health server on port %d", PORT)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        logger.info("Shut down.")


if __name__ == "__main__":
    main()
