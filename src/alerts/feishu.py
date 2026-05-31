"""飞书 Webhook 预警通道。
使用：环境变量 FEISHU_WEBHOOK_URL（机器人 webhook 完整 URL）。
"""
from __future__ import annotations

import os

import requests


def send(text: str) -> str:
    url = os.environ.get("FEISHU_WEBHOOK_URL")
    if not url:
        return "skipped: missing FEISHU_WEBHOOK_URL"
    payload = {
        "msg_type": "text",
        "content": {"text": text},
    }
    r = requests.post(url, json=payload, timeout=10)
    r.raise_for_status()
    return "sent"
