"""Telegram Bot 预警通道。
使用：环境变量 TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID。
"""
from __future__ import annotations

import os

import requests


def send(text: str) -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return "skipped: missing TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, data={
        "chat_id": chat_id, "text": text, "parse_mode": "Markdown",
    }, timeout=10)
    resp.raise_for_status()
    return "sent"
