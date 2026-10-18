"""Sending email over HTTPS (Render's free plan blocks SMTP).

Providers, first one configured wins:
1. Gmail via a Google Apps Script web app (GMAIL_SCRIPT_URL + GMAIL_SCRIPT_SECRET): sent from your own
   Gmail account, so it lands in inboxes reliably; about 100 emails/day on a free Gmail account.
2. Brevo HTTPS API (BREVO_API_KEY + MAIL_FROM_EMAIL).
3. SMTP (SMTP_HOST ...), for servers where SMTP is allowed.
"""
import json
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage

from .. import config

LAST_ERROR = [None]


def provider_name():
    if config.GMAIL_SCRIPT_URL:
        return "Gmail (Apps Script)"
    if config.BREVO_API_KEY:
        return "Brevo"
    if config.SMTP_HOST:
        return "SMTP"
    return None


def configured():
    return provider_name() is not None


def send_email(to, subject, text, html=None):
    """Return True if the provider accepted the message. On failure, LAST_ERROR[0] says why."""
    LAST_ERROR[0] = None
    if config.GMAIL_SCRIPT_URL:
        return _send_gmail_script(to, subject, text, html)
    if config.BREVO_API_KEY:
        return _send_brevo(to, subject, text, html)
    if config.SMTP_HOST:
        return _send_smtp(to, subject, text)
    LAST_ERROR[0] = "No email service is set up (add GMAIL_SCRIPT_URL or BREVO_API_KEY in the server settings)."
    return False


def _fail(msg):
    LAST_ERROR[0] = msg
    print("Email send failed:", msg)
    return False


def _sender():
    return (config.MAIL_FROM_EMAIL or config.SMTP_FROM or config.SMTP_USER or "").strip()


def _send_gmail_script(to, subject, text, html):
    payload = {"secret": config.GMAIL_SCRIPT_SECRET or "", "to": to, "subject": subject, "text": text,
               "html": html or "", "name": config.MAIL_FROM_NAME or config.APP_NAME}
    req = urllib.request.Request(config.GMAIL_SCRIPT_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "text/plain;charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return _fail(f"Gmail script returned HTTP {e.code}. Check the web app URL and that access is set to 'Anyone'.")
    except Exception as e:
        return _fail(f"Could not reach the Gmail script: {e}")
    try:
        out = json.loads(body)
    except ValueError:
        return _fail("The Gmail script did not answer correctly. Re-deploy it as a Web app with access 'Anyone' "
                     "and use the URL ending in /exec.")
    if not out.get("ok"):
        return _fail(f"Gmail script error: {out.get('error') or 'unknown'}")
    return True


def _send_brevo(to, subject, text, html):
    if not _sender():
        return _fail("MAIL_FROM_EMAIL is missing (the sender address you verified in Brevo).")
    payload = {"sender": {"name": config.MAIL_FROM_NAME or config.APP_NAME, "email": _sender()},
               "to": [{"email": to}], "subject": subject, "textContent": text}
    if html:
        payload["htmlContent"] = html
    req = urllib.request.Request("https://api.brevo.com/v3/smtp/email", data=json.dumps(payload).encode(),
                                 headers={"api-key": config.BREVO_API_KEY, "Content-Type": "application/json",
                                          "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 300
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        return _fail(f"Brevo HTTP {e.code}: {detail}")
    except Exception as e:
        return _fail(f"Brevo: {e}")


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
        return _fail(f"SMTP: {e}")
