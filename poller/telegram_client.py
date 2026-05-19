"""Client Telegram minimal — solo invio messaggi via Bot API."""
from __future__ import annotations

import os

import requests


def send_message(text: str, parse_mode: str = "Markdown") -> bool:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[ERR] Telegram send failed: {e}")
        return False
