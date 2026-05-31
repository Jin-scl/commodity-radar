"""Email (SMTP) 预警通道。
使用：环境变量 EMAIL_SMTP_HOST/PORT/USER/PASSWORD/FROM/TO。
"""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText


def send(text: str) -> str:
    host = os.environ.get("EMAIL_SMTP_HOST")
    port = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
    user = os.environ.get("EMAIL_SMTP_USER")
    pwd = os.environ.get("EMAIL_SMTP_PASSWORD")
    sender = os.environ.get("EMAIL_FROM") or user
    to = os.environ.get("EMAIL_TO")
    if not (host and user and pwd and to):
        return "skipped: missing EMAIL_SMTP_* envs"
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = "Commodity Radar Alert"
    msg["From"] = sender
    msg["To"] = to
    with smtplib.SMTP(host, port, timeout=10) as s:
        s.starttls()
        s.login(user, pwd)
        s.sendmail(sender, [to], msg.as_string())
    return "sent"
