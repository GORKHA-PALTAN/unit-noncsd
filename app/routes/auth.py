import re

from ..db import get_db, iso, now_iso, now_utc, parse_iso
from ..security import (audit, create_session, destroy_session, destroy_user_sessions, has_perm, hash_password,
                        password_problem, verify_password, PERMISSIONS)
from ..web import SESSION_COOKIE, ApiError, api, text
from .. import config
from datetime import timedelta

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+\- ]{8,16}$")
DUMMY_HASH = hash_password("timing-equaliser-1")


def public_user(u, csrf=None):
    db = get_db()
    buyer = None
    if u.get("buyer_id"):
        buyer = db.one("SELECT code, company_code, category_code, seniority FROM buyers WHERE id=?", (u["buyer_id"],))
    out = {"id": u["id"], "name": u["name"], "email": u["email"], "phone": u["phone"], "role": u["role"],
           "buyer": buyer, "created_at": u["created_at"]}
    if u["role"] in ("owner", "staff"):
        out["permissions"] = [p for p in list(PERMISSIONS) + ["staff", "settings"] if has_perm(u, p)]
    if csrf:
        out["csrf"] = csrf
    return out


@api("POST", "/api/auth/register", limit="register")
def register(ctx):
    db = get_db()
    name = text(ctx.get("name"), "Name", max_len=80, min_len=2)
    email = text(ctx.get("email"), "Email", max_len=120).lower()
    phone = text(ctx.get("phone"), "Phone", required=False, max_len=16)
    pw = ctx.get("password")
    if not EMAIL_RE.match(email):
        raise ApiError(400, "Enter a valid email address.")
    if phone and not PHONE_RE.match(phone):
        raise ApiError(400, "Enter a valid phone number.")
    prob = password_problem(pw)
    if prob:
        raise ApiError(400, prob)
    if db.one("SELECT id FROM users WHERE email=?", (email,)):
        raise ApiError(409, "An account with this email already exists. Please sign in.")
    uid = db.insert("users", {"name": name, "email": email, "phone": phone, "password_hash": hash_password(pw),
                              "role": "customer", "status": "active", "created_at": now_iso()})
    token, csrf = create_session(uid, ctx.ip, ctx.request.headers.get("user-agent"))
    ctx.set_cookies.append((SESSION_COOKIE, token, config.SESSION_DAYS * 86400))
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    return {"user": public_user(u, csrf)}


@api("POST", "/api/auth/login", limit="login")
def login(ctx):
    db = get_db()
    ident = text(ctx.get("email"), "Email", max_len=120).lower()
    pw = ctx.get("password") or ""
    u = db.one("SELECT * FROM users WHERE email=? OR (phone IS NOT NULL AND phone=?)", (ident, ident))
    if u and u["locked_until"] and parse_iso(u["locked_until"]) > now_utc():
        raise ApiError(429, "Too many failed attempts. This account is locked for a few minutes.")
    ok = verify_password(pw, u["password_hash"] if u else DUMMY_HASH)
    if not u or not ok:
        if u:
            fails = (u["failed_logins"] or 0) + 1
            lock = iso(now_utc() + timedelta(minutes=15)) if fails >= 5 else None
            db.run("UPDATE users SET failed_logins=?, locked_until=? WHERE id=?", (0 if lock else fails, lock, u["id"]))
            if u["role"] != "customer":
                audit(u["id"], "login_failed", "user", u["id"], ip=ctx.ip)
        raise ApiError(401, "Incorrect email or password.")
    if u["status"] != "active":
        raise ApiError(403, "This account has been suspended. Please contact the store.")
    token, csrf = create_session(u["id"], ctx.ip, ctx.request.headers.get("user-agent"))
    ctx.set_cookies.append((SESSION_COOKIE, token, config.SESSION_DAYS * 86400))
    if u["role"] != "customer":
        audit(u["id"], "login", "user", u["id"], ip=ctx.ip)
    return {"user": public_user(u, csrf)}


@api("POST", "/api/auth/logout")
def logout(ctx):
    destroy_session(ctx.request.cookies.get(SESSION_COOKIE))
    ctx.delete_cookies.append(SESSION_COOKIE)
    return {"ok": True}


@api("GET", "/api/auth/me")
def me(ctx):
    if not ctx.user:
        return {"user": None}
    db = get_db()
    counts = {
        "cart": db.val("SELECT COALESCE(SUM(qty),0) FROM cart_items WHERE user_id=?", (ctx.uid,)),
        "wishlist": db.val("SELECT COUNT(*) FROM wishlist WHERE user_id=?", (ctx.uid,)),
        "notifications": db.val("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (ctx.uid,)),
    }
    return {"user": public_user(ctx.user, ctx.csrf), "counts": counts}


@api("POST", "/api/auth/password", auth="user")
def change_password(ctx):
    db = get_db()
    row = db.one("SELECT password_hash FROM users WHERE id=?", (ctx.uid,))
    if row["password_hash"].startswith("!"):
        raise ApiError(400, "This account signs in with an email code or Google, so it has no password to change.")
    if not verify_password(ctx.get("current") or "", row["password_hash"]):
        raise ApiError(400, "Current password is incorrect.")
    prob = password_problem(ctx.get("new"))
    if prob:
        raise ApiError(400, prob)
    db.run("UPDATE users SET password_hash=? WHERE id=?", (hash_password(ctx.get("new")), ctx.uid))
    destroy_user_sessions(ctx.uid, except_token=ctx.request.cookies.get(SESSION_COOKIE))
    audit(ctx.uid, "password_changed", "user", ctx.uid, ip=ctx.ip)
    return {"ok": True}


def _verify_google_credential(credential):
    """Check a Google Sign-In ID token with Google and return its claims (email, name, ...)."""
    import json
    import time
    import urllib.parse
    import urllib.request
    if not config.GOOGLE_CLIENT_ID:
        raise ApiError(400, "Google sign-in is not set up on this store.")
    if not isinstance(credential, str) or not (100 < len(credential) < 5000):
        raise ApiError(400, "Google sign-in failed. Please try again.")
    url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"id_token": credential})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            claims = json.loads(r.read().decode())
    except Exception:
        raise ApiError(401, "Google could not confirm this sign-in. Please try again.")
    if claims.get("aud") != config.GOOGLE_CLIENT_ID:
        raise ApiError(401, "This Google sign-in was not issued for this store.")
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise ApiError(401, "Google sign-in failed. Please try again.")
    if int(claims.get("exp", 0)) < time.time():
        raise ApiError(401, "Google sign-in expired. Please try again.")
    if str(claims.get("email_verified")).lower() != "true" or not claims.get("email"):
        raise ApiError(401, "Your Google email address is not verified.")
    return claims


@api("POST", "/api/auth/google", limit="login")
def google_login(ctx):
    """Sign in (or create a customer account) with a Google account."""
    db = get_db()
    claims = _verify_google_credential(ctx.get("credential"))
    email = claims["email"].strip().lower()
    u = db.one("SELECT * FROM users WHERE email=?", (email,))
    if u and u["role"] != "customer":
        raise ApiError(403, "Staff and owner accounts sign in with their password on the admin page.")
    if u and u["status"] != "active":
        raise ApiError(403, "This account has been suspended. Please contact the store.")
    created = False
    if not u:
        name = (claims.get("name") or email.split("@")[0]).strip()[:80] or "Customer"
        # "!google" can never match a password, so this account signs in only through Google
        uid = db.insert("users", {"name": name, "email": email, "phone": None, "password_hash": "!google",
                                  "role": "customer", "status": "active", "created_at": now_iso()})
        u = db.one("SELECT * FROM users WHERE id=?", (uid,))
        created = True
    token, csrf = create_session(u["id"], ctx.ip, ctx.request.headers.get("user-agent"))
    ctx.set_cookies.append((SESSION_COOKIE, token, config.SESSION_DAYS * 86400))
    return {"user": public_user(u, csrf), "created": created}


# ---------------------------------------------------------------- email one-time codes (customers)

def _code_hash(email, code):
    from ..security import sign
    return sign(f"login-code:{email}:{code}")


def _otp_email(code):
    mins = config.OTP_MINUTES
    store = config.MAIL_FROM_NAME or config.APP_NAME
    text_body = (f"Your {store} sign-in code is {code}\n\nIt expires in {mins} minutes. "
                 "If you didn't ask for this code, you can ignore this email. Never share this code with anyone.")
    html = (f"<div style='font-family:Arial,sans-serif;max-width:420px;margin:auto;padding:24px;color:#1d1f2b'>"
            f"<h2 style='margin:0 0 8px'>{store}</h2><p>Your sign-in code is:</p>"
            f"<p style='font-size:34px;font-weight:700;letter-spacing:8px;margin:12px 0;color:#1f8a84'>{code}</p>"
            f"<p style='color:#4a4e60'>It expires in {mins} minutes. If you didn't ask for this code, ignore this email. "
            f"Never share this code with anyone.</p></div>")
    return f"{code} is your {store} sign-in code", text_body, html


@api("POST", "/api/auth/otp/request", limit="otp_send")
def otp_request(ctx):
    """Email a 6-digit sign-in code to a customer (new or existing)."""
    import secrets
    from ..services import mailer
    db = get_db()
    email = text(ctx.get("email"), "Email", max_len=120).lower()
    if not EMAIL_RE.match(email):
        raise ApiError(400, "Enter a valid email address.")
    u = db.one("SELECT role, status FROM users WHERE email=?", (email,))
    if u and u["role"] != "customer":
        raise ApiError(403, "Staff and owner accounts sign in with their password on the admin page.")
    if u and u["status"] != "active":
        raise ApiError(403, "This account has been suspended. Please contact the store.")
    now = now_utc()
    last = db.one("SELECT created_at FROM login_codes WHERE email=? ORDER BY id DESC LIMIT 1", (email,))
    if last and (now - parse_iso(last["created_at"])).total_seconds() < 45:
        raise ApiError(429, "A code was just sent. Please wait a minute before asking for another.")
    recent = db.val("SELECT COUNT(*) FROM login_codes WHERE email=? AND created_at>?", (email, iso(now - timedelta(hours=1))))
    if recent >= 5:
        raise ApiError(429, "Too many codes requested for this email. Please try again in an hour.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    # only the newest code works
    db.run("UPDATE login_codes SET used_at=? WHERE email=? AND used_at IS NULL", (now_iso(), email))
    db.insert("login_codes", {"email": email, "code_hash": _code_hash(email, code), "attempts": 0, "ip": ctx.ip,
                              "created_at": iso(now), "expires_at": iso(now + timedelta(minutes=config.OTP_MINUTES))})
    if mailer.configured():
        subject, body, html = _otp_email(code)
        if not mailer.send_email(email, subject, body, html):
            raise ApiError(502, "We couldn't send the email right now. Please try again in a minute.")
    else:
        # No email service yet (local testing): the code appears in the server window/log only.
        print(f"[login code] {email}: {code}  (set BREVO_API_KEY to email codes to customers)")
    return {"sent": True, "minutes": config.OTP_MINUTES}


@api("POST", "/api/auth/otp/verify", limit="otp_verify")
def otp_verify(ctx):
    """Check the emailed code, then sign in (creating the customer account on first use)."""
    import hmac
    db = get_db()
    email = text(ctx.get("email"), "Email", max_len=120).lower()
    code = re.sub(r"\D", "", str(ctx.get("code") or ""))
    if len(code) != 6:
        raise ApiError(400, "Enter the 6-digit code from the email.")
    row = db.one("SELECT * FROM login_codes WHERE email=? AND used_at IS NULL ORDER BY id DESC LIMIT 1", (email,))
    if not row or parse_iso(row["expires_at"]) < now_utc():
        raise ApiError(400, "This code has expired. Tap \"Resend code\" to get a new one.")
    if row["attempts"] >= 5:
        db.run("UPDATE login_codes SET used_at=? WHERE id=?", (now_iso(), row["id"]))
        raise ApiError(400, "Too many wrong tries. Tap \"Resend code\" to get a new one.")
    if not hmac.compare_digest(row["code_hash"], _code_hash(email, code)):
        db.run("UPDATE login_codes SET attempts=attempts+1 WHERE id=?", (row["id"],))
        left = 4 - row["attempts"]
        raise ApiError(400, f"That code is not right. {left} {'try' if left == 1 else 'tries'} left." if left > 0
                       else "That code is not right. Tap \"Resend code\" to get a new one.")
    u = db.one("SELECT * FROM users WHERE email=?", (email,))
    if u and u["role"] != "customer":
        raise ApiError(403, "Staff and owner accounts sign in with their password on the admin page.")
    if u and u["status"] != "active":
        raise ApiError(403, "This account has been suspended. Please contact the store.")
    created = False
    if not u:
        name = (ctx.get("name") or "").strip()
        if not name:
            return {"need_name": True}  # code stays valid; the page asks for the customer's name
        name = text(name, "Name", max_len=80, min_len=2)
        phone = text(ctx.get("phone"), "Phone", required=False, max_len=16)
        if phone and not PHONE_RE.match(phone):
            raise ApiError(400, "Enter a valid phone number.")
        uid = db.insert("users", {"name": name, "email": email, "phone": phone, "password_hash": "!otp",
                                  "role": "customer", "status": "active", "created_at": now_iso()})
        u = db.one("SELECT * FROM users WHERE id=?", (uid,))
        created = True
    db.run("UPDATE login_codes SET used_at=? WHERE id=?", (now_iso(), row["id"]))
    db.run("UPDATE users SET failed_logins=0, locked_until=NULL WHERE id=?", (u["id"],))
    token, csrf = create_session(u["id"], ctx.ip, ctx.request.headers.get("user-agent"))
    ctx.set_cookies.append((SESSION_COOKIE, token, config.SESSION_DAYS * 86400))
    return {"user": public_user(u, csrf), "created": created}
