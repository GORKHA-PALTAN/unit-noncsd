"""Shared helpers: store settings, notifications, product serialisation, money."""
import re
import smtplib
import threading
from email.message import EmailMessage

from .. import config
from ..db import get_db, jdump, jload, now_iso

DEFAULT_SETTINGS = {
    "store_name": config.APP_NAME,
    "tagline": "Quality goods for the unit, delivered.",
    "announcement": "Free delivery on orders above ₹999 · Sample catalogue for demonstration",
    "support_email": "support@unit.local",
    "support_phone": "+91 00000 00000",
    "currency": "INR",
    "prices_include_tax": True,
    "default_tax_rate": 18,
    "cod_enabled": True,
    "cod_max_amount": 20000,
    "razorpay_enabled": True,
    "sandbox_enabled": True,
    "upi_enabled": False,
    "upi_id": "",
    "upi_payee_name": "",
    "payment_expiry_minutes": 30,
    "return_window_days": 7,
    "cancel_before_status": "packed",
    "low_stock_default": 10,
    "reorder_lead_days": 7,
    "max_qty_per_order": 10,
    "policy_returns": "Eligible items can be returned within the return window after delivery. Refunds go to the original payment method; cash-on-delivery refunds are settled by the unit store.",
    "policy_shipping": "Orders are dispatched from the unit store. Delivery estimates are shown at checkout.",
    "public_url": "",
    "policy_privacy": "Customer details are used only to process and deliver orders and are visible only to authorised staff.",
}


def get_settings(include_private=False):
    db = get_db()
    out = dict(DEFAULT_SETTINGS)
    for row in db.all("SELECT key, value FROM settings"):
        if row["key"].startswith("_"):
            continue
        out[row["key"]] = jload(row["value"], row["value"])
    return out


def set_settings(values):
    db = get_db()
    for k, v in values.items():
        if k.startswith("_") or k not in DEFAULT_SETTINGS:
            continue
        if db.one("SELECT key FROM settings WHERE key=?", (k,)):
            db.run("UPDATE settings SET value=? WHERE key=?", (jdump(v), k))
        else:
            db.run("INSERT INTO settings(key, value) VALUES (?, ?)", (k, jdump(v)))


def money(x):
    return round(float(x or 0) + 1e-9, 2)


def slugify(s):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:80] or "item"


def unique_slug(table, base, exclude_id=None):
    db = get_db()
    slug, n = slugify(base), 1
    candidate = slug
    while True:
        row = db.one(f"SELECT id FROM {table} WHERE slug=?", (candidate,))
        if not row or row["id"] == exclude_id:
            return candidate
        n += 1
        candidate = f"{slug}-{n}"


def available(p):
    return max(0, int(p["physical_stock"]) - int(p["reserved_qty"]) - int(p["unavailable_qty"]))


def discount_pct(p):
    mrp, sp = p.get("mrp") or 0, p.get("selling_price") or 0
    if mrp and mrp > sp:
        return int(round((mrp - sp) / mrp * 100))
    return 0


def stock_label(p):
    if p["status"] == "out_of_stock":
        return "out"
    a = available(p)
    if a <= 0:
        return "out"
    if a <= (p.get("low_stock_threshold") or 0):
        return "low"
    return "in"


def first_images(product_ids):
    if not product_ids:
        return {}
    db = get_db()
    marks = ",".join("?" for _ in product_ids)
    rows = db.all(f"SELECT product_id, url FROM product_images WHERE product_id IN ({marks}) ORDER BY sort, id", product_ids)
    out = {}
    for r in rows:
        out.setdefault(r["product_id"], r["url"])
    return out


def product_card(p, img=None):
    a = available(p)
    return {
        "id": p["id"], "name": p["name"], "slug": p["slug"], "brand": p["brand"],
        "price": money(p["selling_price"]), "mrp": money(p["mrp"]) if p.get("mrp") else None,
        "discount": discount_pct(p), "rating": round(p["rating_avg"] or 0, 1), "reviews": p["rating_count"],
        "stock": stock_label(p), "available": a if a <= (p.get("low_stock_threshold") or 10) else None,
        "image": img or "/static/common/placeholder.svg", "sample": bool(p["is_sample"]),
        "category_id": p["category_id"],
    }


def notify(user_id, title, body, link=None, email=True):
    db = get_db()
    db.insert("notifications", {"user_id": user_id, "title": title, "body": body, "link": link, "created_at": now_iso()})
    from . import mailer
    if email and mailer.configured():
        row = db.one("SELECT email, is_sample FROM users WHERE id=?", (user_id,))
        if row and row["email"] and not row["is_sample"]:
            threading.Thread(target=_send_mail, args=(row["email"], title, body), daemon=True).start()


def _send_mail(to, subject, body):
    from . import mailer
    if config.BREVO_API_KEY:
        mailer.send_email(to, f"{config.APP_NAME}: {subject}", body)
        return
    try:
        msg = EmailMessage()
        msg["From"] = config.SMTP_FROM or config.SMTP_USER
        msg["To"] = to
        msg["Subject"] = f"{config.APP_NAME}: {subject}"
        msg.set_content(body)
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as s:
            s.starttls()
            if config.SMTP_USER:
                s.login(config.SMTP_USER, config.SMTP_PASSWORD or "")
            s.send_message(msg)
    except Exception as e:  # email is best-effort; in-app notification already stored
        print("Email send failed:", e)


def bump_activity(product_id, field, day):
    if field not in ("views", "add_to_cart", "wishlist"):
        return
    db = get_db()
    n = db.run(f"UPDATE activity_daily SET {field}={field}+1 WHERE day=? AND product_id=?", (day, product_id))
    if not n:
        try:
            db.run(f"INSERT INTO activity_daily(day, product_id, {field}) VALUES (?, ?, 1)", (day, product_id))
        except Exception:
            db.run(f"UPDATE activity_daily SET {field}={field}+1 WHERE day=? AND product_id=?", (day, product_id))


def log_search(query, results, day):
    db = get_db()
    q = query.strip().lower()[:80]
    if not q:
        return
    n = db.run("UPDATE search_log SET count=count+1, results=? WHERE day=? AND query=?", (results, day, q))
    if not n:
        try:
            db.run("INSERT INTO search_log(day, query, results, count) VALUES (?, ?, ?, 1)", (day, q, results))
        except Exception:
            pass


# ---------------- stored files (product images) ----------------
# Files are kept in the database so they survive on cloud hosts whose disks are wiped on restart.
# The local uploads/ folder is only a cache.
def save_file(rel_path, mime, data):
    db = get_db()
    if db.one("SELECT id FROM files WHERE path=?", (rel_path,)):
        db.run("UPDATE files SET mime=?, data=? WHERE path=?", (mime, data, rel_path))
    else:
        db.insert("files", {"path": rel_path, "mime": mime, "data": data, "created_at": now_iso()})
    try:
        target = config.UPLOAD_DIR / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError:
        pass


def delete_file(rel_path):
    get_db().run("DELETE FROM files WHERE path=?", (rel_path,))
    try:
        (config.UPLOAD_DIR / rel_path).unlink()
    except OSError:
        pass


def load_file(rel_path):
    row = get_db().one("SELECT mime, data FROM files WHERE path=?", (rel_path,))
    return (row["mime"], bytes(row["data"])) if row else None
