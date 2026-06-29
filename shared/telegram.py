import logging
import requests
from shared.config import TELEGRAM_BOT_TOKEN

logger = logging.getLogger("telegram")

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def delete_webhook() -> bool:
    """Delete any existing webhook so getUpdates polling works."""
    try:
        resp = requests.post(f"{BASE_URL}/deleteWebhook", timeout=10)
        result = resp.json() if resp.ok else {}
        logger.info("deleteWebhook: %s", result)
        return result.get("result", False)
    except Exception as e:
        logger.error("Failed to delete webhook: %s", e)
        return False


def get_webhook_info() -> dict:
    try:
        resp = requests.get(f"{BASE_URL}/getWebhookInfo", timeout=10)
        if resp.ok:
            return resp.json().get("result", {})
    except Exception as e:
        logger.error("Failed to get webhook info: %s", e)
    return {}


def get_updates(offset: int = 0) -> list:
    try:
        resp = requests.get(
            f"{BASE_URL}/getUpdates",
            params={"offset": offset, "timeout": 30},
            timeout=35,
        )
        if resp.ok:
            return resp.json().get("result", [])
    except Exception as e:
        logger.error("Failed to get updates: %s", e)
    return []


def get_file_url(file_id: str) -> str | None:
    try:
        resp = requests.get(f"{BASE_URL}/getFile", params={"file_id": file_id}, timeout=10)
        if resp.ok:
            file_path = resp.json().get("result", {}).get("file_path")
            if file_path:
                return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    except Exception as e:
        logger.error("Failed to get file: %s", e)
    return None


def download_file(file_id: str) -> bytes | None:
    url = get_file_url(file_id)
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=30)
        if resp.ok:
            return resp.content
    except Exception as e:
        logger.error("Failed to download file: %s", e)
    return None


def send_message(chat_id: str, text: str, reply_to_message_id: int = None) -> dict | None:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    try:
        resp = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=10)
        if resp.ok:
            return resp.json().get("result")
    except Exception as e:
        logger.error("Failed to send message: %s", e)
    return None


def send_error_alert(skill_name: str, action: str, error: str):
    from shared.config import TELEGRAM_CHAT_ID_SNOWFIT
    text = f"⚠️ *{skill_name}* error in `{action}`:\n```\n{error}\n```"
    send_message(TELEGRAM_CHAT_ID_SNOWFIT, text)
