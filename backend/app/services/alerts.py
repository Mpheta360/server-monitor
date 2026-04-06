import atexit
import json
import smtplib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.message import EmailMessage
from urllib import error, request

from ..config import settings
from .types import AlertResult


class AlertDispatcher:
    """Dispatches alerts to stdout + optional Telegram/webhook sinks with cooldown."""

    def __init__(self) -> None:
        self._last_sent: dict[str, datetime] = {}
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="alert-dispatch")
        atexit.register(self._shutdown_executor)

    def _shutdown_executor(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)

    def _within_cooldown(self, key: str) -> bool:
        cooldown = max(settings.alert_cooldown_seconds, 0)
        if cooldown == 0:
            return False

        last = self._last_sent.get(key)
        if not last:
            return False

        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        return elapsed < cooldown

    def _post_json(self, url: str, payload: dict) -> bool:
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=5) as resp:
                return 200 <= resp.status < 300
        except (error.URLError, TimeoutError):
            return False

    def _send_telegram(self, message: str) -> bool:
        token = settings.telegram_bot_token.strip()
        chat_id = settings.telegram_chat_id.strip()
        if not token or not chat_id:
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
        }
        return self._post_json(url, payload)

    def _send_webhook(self, key: str, severity: str, message: str) -> bool:
        webhook_url = settings.alert_webhook_url.strip()
        if not webhook_url:
            return False

        payload = {
            "key": key,
            "severity": severity,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return self._post_json(webhook_url, payload)

    def _send_email(self, key: str, severity: str, message: str) -> bool:
        recipients = [email.strip() for email in settings.alert_email_to.split(",") if email.strip()]
        smtp_host = settings.smtp_host.strip()
        smtp_username = settings.smtp_username.strip()
        if not recipients and smtp_username and "@" in smtp_username:
            recipients = [smtp_username]

        if not smtp_host or not recipients:
            return False

        sender = settings.alert_email_from.strip() or smtp_username or "monitor@localhost"
        subject = f"[System Monitor][{severity.upper()}] {key}"
        body = (
            f"Alert key: {key}\n"
            f"Severity: {severity}\n"
            f"Time (UTC): {datetime.now(timezone.utc).isoformat()}\n\n"
            f"{message}\n"
        )

        email_message = EmailMessage()
        email_message["Subject"] = subject
        email_message["From"] = sender
        email_message["To"] = ", ".join(recipients)
        email_message.set_content(body)

        smtp_password = settings.smtp_password

        try:
            if settings.smtp_use_ssl:
                with smtplib.SMTP_SSL(
                    host=smtp_host,
                    port=settings.smtp_port,
                    timeout=settings.smtp_timeout_seconds,
                ) as smtp:
                    if smtp_username:
                        smtp.login(smtp_username, smtp_password)
                    smtp.send_message(email_message)
                    return True

            with smtplib.SMTP(
                host=smtp_host,
                port=settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
            ) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if smtp_username:
                    smtp.login(smtp_username, smtp_password)
                smtp.send_message(email_message)
                return True
        except (smtplib.SMTPException, OSError, TimeoutError):
            return False

    def _safe_send(self, channel: str, fn, *args) -> None:
        try:
            ok = fn(*args)
            if not ok:
                print(f"[ALERT][{channel.upper()}] delivery failed")
        except Exception as exc:  # pragma: no cover - defensive path
            print(f"[ALERT][{channel.upper()}] delivery error: {exc}")

    def dispatch(self, key: str, severity: str, message: str) -> AlertResult:
        if self._within_cooldown(key):
            return AlertResult(delivered=False, suppressed=True, detail="Suppressed by cooldown")

        print(f"[ALERT][{severity.upper()}] {message}")

        queued_channels: list[str] = []

        if settings.telegram_bot_token.strip() and settings.telegram_chat_id.strip():
            self._executor.submit(self._safe_send, "telegram", self._send_telegram, message)
            queued_channels.append("telegram")

        if settings.alert_webhook_url.strip():
            self._executor.submit(self._safe_send, "webhook", self._send_webhook, key, severity, message)
            queued_channels.append("webhook")

        email_recipients = [email.strip() for email in settings.alert_email_to.split(",") if email.strip()]
        smtp_username = settings.smtp_username.strip()
        if not email_recipients and smtp_username and "@" in smtp_username:
            email_recipients = [smtp_username]
        if settings.smtp_host.strip() and email_recipients:
            self._executor.submit(self._safe_send, "email", self._send_email, key, severity, message)
            queued_channels.append("email")

        self._last_sent[key] = datetime.now(timezone.utc)
        if queued_channels:
            channels = ", ".join(queued_channels)
            return AlertResult(delivered=True, suppressed=False, detail=f"Queued delivery via: {channels}")

        return AlertResult(
            delivered=False,
            suppressed=False,
            detail="No remote sink configured or delivery failed; logged locally",
        )
