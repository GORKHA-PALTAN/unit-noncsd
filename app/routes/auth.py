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
    if not verify_password(ctx.get("current") or "", row["password_hash"]):
        raise ApiError(400, "Current password is incorrect.")
    prob = password_problem(ctx.get("new"))
    if prob:
        raise ApiError(400, prob)
    db.run("UPDATE users SET password_hash=? WHERE id=?", (hash_password(ctx.get("new")), ctx.uid))
    destroy_user_sessions(ctx.uid, except_token=ctx.request.cookies.get(SESSION_COOKIE))
    audit(ctx.uid, "password_changed", "user", ctx.uid, ip=ctx.ip)
    return {"ok": True}
