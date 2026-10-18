"""Sending email. Uses the Brevo HTTPS API when BREVO_API_KEY is set (works on hosts that block SMTP,
such as Render's free plan); otherwise falls back to SMTP settings if present."""
import json
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage

from .. import config


def configured():
    return bool(config.BREVO_API_KEY or config.SMTP_HOST)


def provider_name():
    if config.BREVO_API_KEY:
        return "Brevo"
    if config.SMTP_HOST:
        return "SMTP"
    return None


def send_email(to, subject, text, html=None):
    """Return True if the message was handed to the email provider."""
    if config.BREVO_API_KEY:
        return _send_brevo(to, subject, text, html)
    if config.SMTP_HOST:
        return _send_smtp(to, subject, text)
    return False


def _sender():
    return (config.MAIL_FROM_EMAIL or config.SMTP_FROM or config.SMTP_USER or "").strip()


def _send_brevo(to, subject, text, html):
    payload = {
        "sender": {"name": config.MAIL_FROM_NAME or config.APP_NAME, "email": _sender()},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": text,
    }
    if html:
        payload["htmlContent"] = html
    req = urllib.request.Request("https://api.brevo.com/v3/smtp/email", data=json.dumps(payload).encode(),
                                 headers={"api-key": config.BREVO_API_KEY, "Content-Type": "application/json",
                                          "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 300
    except urllib.error.HTTPError as e:
        print("Email send failed (Brevo):", e.code, e.read()[:300])
    except Exception as e:
        print("Email send failed (Brevo):", e)
    return False


def _send_smtp(to, subject, text):
    try:
        msg = EmailMessage()
        msg["From"] = _sender()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as s:
            s.starttls()
            if config.SMTP_USER:
                s.login(config.SMTP_USER, config.SMTP_PASSWORD or "")
            s.send_message(msg)
        return True
    except Exception as e:
        print("Email send failed (SMTP):", e)
        return False
