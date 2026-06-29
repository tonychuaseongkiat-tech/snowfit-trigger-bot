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
from shared.telegram import get_updates, download_file, send_message, send_error_alert, delete_webhook, get_webhook_info
from handler import parse_caption, parse_delivery, convert_invoice_to_pi
from vision import extract_order_details, extract_order_from_pdf
from sheet_writer import write_order
from drive_reader import download_invoice_pdf

SGT = timezone(timedelta(hours=8))
PORT = int(os.environ.get("PORT", 8080))
POLL_INTERVAL = 2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("snowfit-trigger-bot")


def process_order_message(message: dict):
    """Process a /order message with photo. Supports multiple invoice numbers."""
    chat_id = str(message["chat"]["id"])
    message_id = message["message_id"]
    caption = message.get("caption", "")

    parsed = parse_caption(caption)
    if not parsed:
        send_message(chat_id, "❌ Could not parse caption. Expected format:\n/order\n0626-0037\nDelivery [date/month]\n[Pending]", message_id)
        return

    invoices = parsed["invoices"]
    logger.info("Processing %d order(s): %s (pending=%s)",
                len(invoices), [i["pi_no"] for i in invoices], parsed["is_pending"])

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

    extracted_list = extract_order_details(photo_bytes)
    if not extracted_list:
        send_message(chat_id, "❌ Could not extract order details from photo. Please try with a clearer image.", message_id)
        return

    if len(extracted_list) < len(invoices):
        logger.warning("Photo has %d items but caption has %d invoices — padding with last extracted",
                       len(extracted_list), len(invoices))
        while len(extracted_list) < len(invoices):
            extracted_list.append(extracted_list[-1])

    results = []
    for i, invoice in enumerate(invoices):
        extracted = extracted_list[i] if i < len(extracted_list) else extracted_list[-1]

        single_parsed = {
            "invoice_raw": invoice["invoice_raw"],
            "pi_no": invoice["pi_no"],
            "delivery_raw": parsed["delivery_raw"],
            "delivery_date": parsed.get("delivery_date"),
            "delivery_month_year": parsed.get("delivery_month_year"),
            "has_specific_date": parsed["has_specific_date"],
            "is_pending": parsed["is_pending"],
        }

        try:
            result = write_order(single_parsed, extracted)
            results.append(result)
        except Exception as e:
            logger.error("Sheet write failed for %s: %s", invoice["pi_no"], e, exc_info=True)
            results.append({"status": "error", "pi_no": invoice["pi_no"], "reason": str(e)})

    reply_lines = []
    for r in results:
        if r["status"] == "ok":
            emoji = "📋" if r["section"] == "Pending" else "✅"
            reply_lines.append(f"{emoji} *{r['pi_no']}* → *{r['section']}* (row {r['row']}) — Delivery {r['delivery']}")
        else:
            reply_lines.append(f"❌ *{r.get('pi_no', '?')}* — {r.get('reason', 'unknown error')}")

    send_message(chat_id, "\n".join(reply_lines), message_id)


def process_pdf_trigger(order_id: str) -> dict:
    """Process a bedframe order from invoice PDF on Google Drive."""
    logger.info("PDF trigger for %s", order_id)

    pdf_bytes = download_invoice_pdf(order_id)
    if not pdf_bytes:
        return {"status": "error", "reason": f"PDF not found for {order_id}"}

    extracted = extract_order_from_pdf(pdf_bytes)
    if not extracted:
        return {"status": "error", "reason": f"Gemini extraction failed for {order_id}"}

    pi_no = convert_invoice_to_pi(order_id)

    delivery_text = extracted.get("delivery_text", "")
    delivery_info = parse_delivery(f"Delivery {delivery_text}") if delivery_text else None

    if delivery_info and delivery_info["has_specific_date"]:
        is_pending = False
    else:
        is_pending = True

    parsed_caption = {
        "invoice_raw": order_id,
        "pi_no": pi_no,
        "delivery_raw": delivery_info["raw"] if delivery_info else "",
        "delivery_date": delivery_info.get("date") if delivery_info else None,
        "delivery_month_year": delivery_info.get("month_year") if delivery_info else None,
        "has_specific_date": delivery_info["has_specific_date"] if delivery_info else False,
        "is_pending": is_pending,
    }

    result = write_order(parsed_caption, extracted)
    logger.info("PDF trigger result for %s: %s", order_id, result)
    return result


def start_polling():
    """Poll Telegram for /order messages with photos."""
    logger.info("Starting Telegram polling...")
    logger.info("Bot token set: %s", bool(TELEGRAM_BOT_TOKEN))
    logger.info("Chat ID: %s", TELEGRAM_CHAT_ID_SNOWFIT)

    webhook_info = get_webhook_info()
    logger.info("Current webhook: %s", webhook_info.get("url", "(none)"))
    if webhook_info.get("url"):
        logger.info("Clearing existing webhook...")
        delete_webhook()
    else:
        delete_webhook()
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

                if str(chat_id) != TELEGRAM_CHAT_ID_SNOWFIT:
                    continue

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

    def do_POST(self):
        if self.path == "/trigger/bedframe":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                order_id = data.get("order_id", "")
                if not order_id:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "order_id required"}).encode())
                    return

                result = process_pdf_trigger(order_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            except Exception as e:
                logger.error("Trigger error: %s", e, exc_info=True)
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
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
