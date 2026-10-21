"""Authentication, sessions, CSRF, rate limiting and role-based permissions (all server-side)."""
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from . import config
from .db import get_db, iso, now_iso, now_utc, parse_iso, jload

# ---------------- permissions ----------------
PERMISSIONS = {
    "products": "Products & categories",
    "inventory": "Inventory & stock adjustments",
    "orders": "Orders & delivery status",
    "customers": "Customer details & accounts",
    "returns": "Returns, cancellations & refunds",
    "analytics": "AI insights & forecasts",
    "reports": "Reports & data exports",
    "finance": "Revenue, expenses & profit",
    "marketing": "Banners, coupons & promotions",
    "buyers": "Unit buyer codes",
}
OWNER_ONLY = {"staff", "settings"}


def has_perm(user, perm):
    if not user:
        return False
    if user["role"] == "owner":
        return True
    if user["role"] != "staff" or perm in OWNER_ONLY:
        return False
    return perm in (jload(user.get("permissions"), []) or [])


# ---------------- passwords ----------------
PBKDF2_ITER = 240_000


def hash_password(pw):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ITER)
    return f"pbkdf2_sha256${PBKDF2_ITER}${salt.hex()}${dk.hex()}"


def verify_password(pw, stored):
    try:
        algo, it, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), dk)
    except (ValueError, AttributeError):
        return False


def password_problem(pw):
    if not isinstance(pw, str) or len(pw) < 8:
        return "Password must be at least 8 characters."
    if len(pw) > 128:
        return "Password is too long."
    if not any(c.isdigit() for c in pw) or not any(c.isalpha() for c in pw):
        return "Password must contain letters and numbers."
    return None


# ---------------- sessions ----------------
def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id, ip=None, ua=None):
    db = get_db()
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    db.insert("sessions", {
        "token_hash": _token_hash(token), "user_id": user_id, "csrf": csrf,
        "created_at": now_iso(), "expires_at": iso(now_utc() + timedelta(days=config.SESSION_DAYS)),
        "ip": ip, "ua": (ua or "")[:200],
    })
    db.run("UPDATE users SET last_login_at=?, failed_logins=0, locked_until=NULL WHERE id=?", (now_iso(), user_id))
    return token, csrf


def load_session(token):
    if not token:
        return None, None
    db = get_db()
    row = db.one(
        "SELECT s.id AS sid, s.csrf, s.expires_at, u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?",
        (_token_hash(token),),
    )
    if not row:
        return None, None
    if parse_iso(row["expires_at"]) < now_utc() or row["status"] != "active":
        db.run("DELETE FROM sessions WHERE id=?", (row["sid"],))
        return None, None
    csrf = row.pop("csrf")
    row.pop("password_hash", None)
    return row, csrf


def destroy_session(token):
    if token:
        get_db().run("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


def destroy_user_sessions(user_id, except_token=None):
    db = get_db()
    if except_token:
        db.run("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user_id, _token_hash(except_token)))
    else:
        db.run("DELETE FROM sessions WHERE user_id=?", (user_id,))


# ---------------- rate limiting (in-memory sliding window per client) ----------------
_buckets = defaultdict(deque)
_rl_lock = threading.Lock()

LIMITS = {
    "login": (10, 300),
    "otp_send": (6, 900),
    "otp_verify": (20, 900),
    "register": (6, 3600),
    "vendor_apply": (5, 3600),
    "order": (20, 600),
    "pay": (30, 600),
    "review": (10, 3600),
    "write": (240, 60),
    "read": (600, 60),
    "track": (300, 60),
}


def rate_limited(key, client):
    limit, window = LIMITS.get(key, (300, 60))
    limit = int(limit * config.RATE_LIMIT_SCALE)
    now = time.monotonic()
    with _rl_lock:
        q = _buckets[(key, client)]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return int(window - (now - q[0])) + 1
        q.append(now)
    return 0


def reset_rate_limits():
    with _rl_lock:
        _buckets.clear()


# ---------------- signing (sandbox payment tokens) ----------------
_secret = None


def secret_key():
    global _secret
    if _secret:
        return _secret
    if config.SECRET_KEY:
        _secret = config.SECRET_KEY.encode()
        return _secret
    db = get_db()
    row = db.one("SELECT value FROM settings WHERE key='_secret_key'")
    if row:
        _secret = row["value"].encode()
    else:
        val = secrets.token_hex(32)
        db.run("INSERT INTO settings(key, value) VALUES ('_secret_key', ?)", (val,))
        _secret = val.encode()
    return _secret


def sign(message):
    return hmac.new(secret_key(), message.encode(), hashlib.sha256).hexdigest()


def audit(actor_id, action, entity=None, entity_id=None, detail=None, ip=None):
    get_db().insert("audit_log", {
        "actor_id": actor_id, "action": action, "entity": entity,
        "entity_id": str(entity_id) if entity_id is not None else None,
        "detail": (detail or "")[:1000], "ip": ip, "created_at": now_iso(),
    })
