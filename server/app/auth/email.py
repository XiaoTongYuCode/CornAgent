"""Pluggable email delivery. No vendor-specific account or logging of codes."""

import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol


class EmailSender(Protocol):
    def send_code(self, recipient: str, code: str) -> None: ...


class SmtpEmailSender:
    def __init__(self, settings):
        self.settings = settings

    def send_code(self, recipient: str, code: str) -> None:
        s = self.settings
        message = EmailMessage()
        message["From"] = s.auth_smtp_from
        message["To"] = recipient
        message["Subject"] = "CornAgent verification code"
        message.set_content(
            f"Your CornAgent verification code is {code}. It expires in 10 minutes."
        )
        with smtplib.SMTP(s.auth_smtp_host, s.auth_smtp_port, timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if s.auth_smtp_username:
                smtp.login(s.auth_smtp_username, s.auth_smtp_password.get_secret_value())
            smtp.send_message(message)
