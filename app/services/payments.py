"""Payments. An order is marked paid ONLY after server-side verification:

* Razorpay: HMAC-SHA256 signature check with the secret key (never sent to the browser), plus an
  API lookup of the payment status when reachable, plus signed webhooks.
* Sandbox (test mode): a server-signed, single-use token; clearly labelled as a simulation.
* Cash on Delivery: marked paid only when staff record the cash collection.
"""
import base64
import hashlib
import hmac
import json
import secrets
import urllib.error
import urllib.request

from .. import config
from ..db import get_db, now_iso, transaction
from ..security import sign
from ..web import ApiError
from .common import get_settings, notify
from .orders import mark_paid, payment_method_allowed

RZP_API = "https://api.razorpay.com/v1"


def _rzp_request(method, path, payload=None):
    auth = base64.b64encode(f"{config.RAZORPAY_KEY_ID}:{config.RAZORPAY_KEY_SECRET}".encode()).decode()
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(RZP_API + path, data=data, method=method,
                                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        raise ApiError(502, f"Payment gateway error: {detail}")
    except urllib.error.URLError:
        raise ApiError(502, "Could not reach the payment gateway. Please try again.")


def start_payment(order, user, method=None):
    db = get_db()
    if order["status"] != "payment_pending" or order["payment_status"] not in ("pending", "failed"):
        raise ApiError(400, "This order is not awaiting payment.")
    method = method or order["payment_method"]
    if method not in ("razorpay", "sandbox", "upi"):
        raise ApiError(400, "Choose an online payment method.")
    ok, msg = payment_method_allowed(method, order["grand_total"])
    if not ok:
        raise ApiError(400, msg)
    amount = float(order["grand_total"])
    if method == "upi":
        return _start_upi(order, amount)
    if method == "razorpay":
        rzp = _rzp_request("POST", "/orders", {"amount": int(round(amount * 100)), "currency": "INR",
                                               "receipt": order["order_no"], "notes": {"order_no": order["order_no"]}})
        pid = db.insert("payments", {"order_id": order["id"], "method": "razorpay", "provider_order_id": rzp["id"],
                                     "amount": amount, "status": "created", "created_at": now_iso()})
        db.run("UPDATE orders SET payment_method='razorpay' WHERE id=?", (order["id"],))
        s = get_settings()
        return {"method": "razorpay", "payment_id": pid, "key_id": config.RAZORPAY_KEY_ID, "razorpay_order_id": rzp["id"],
                "amount": int(round(amount * 100)), "currency": "INR", "name": s["store_name"],
                "description": f"Order {order['order_no']}",
                "prefill": {"name": user["name"], "email": user.get("email") or "", "contact": user.get("phone") or ""}}
    nonce = secrets.token_hex(16)
    pid = db.insert("payments", {"order_id": order["id"], "method": "sandbox", "provider_order_id": f"sbx_{nonce[:12]}",
                                 "amount": amount, "status": "created", "token_nonce": nonce, "created_at": now_iso()})
    db.run("UPDATE orders SET payment_method='sandbox' WHERE id=?", (order["id"],))
    token = sign(f"{pid}:{order['id']}:{amount:.2f}:{nonce}")
    return {"method": "sandbox", "payment_id": pid, "token": token, "amount": amount,
            "notice": "TEST MODE — this is a simulated payment. No real money is charged."}


def verify_razorpay_signature(order_id, payment_id, signature, secret=None):
    secret = secret or config.RAZORPAY_KEY_SECRET or ""
    expected = hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def verify_razorpay(user, rzp_order_id, rzp_payment_id, signature):
    db = get_db()
    pay = db.one("SELECT p.*, o.user_id FROM payments p JOIN orders o ON o.id=p.order_id "
                 "WHERE p.provider_order_id=? AND p.method='razorpay'", (rzp_order_id,))
    if not pay or pay["user_id"] != user["id"]:
        raise ApiError(404, "Payment not found.")
    if not config.razorpay_configured():
        raise ApiError(400, "Razorpay is not configured.")
    if not verify_razorpay_signature(rzp_order_id, rzp_payment_id, signature):
        db.run("UPDATE payments SET status='failed', error='signature mismatch' WHERE id=?", (pay["id"],))
        db.run("UPDATE orders SET payment_status='failed' WHERE id=? AND payment_status='pending'", (pay["order_id"],))
        raise ApiError(400, "Payment could not be verified. You have not been charged for this order; please retry.")
    # Double-check with Razorpay that the payment is really authorised/captured for the right amount
    info = _rzp_request("GET", f"/payments/{rzp_payment_id}")
    if info.get("order_id") != rzp_order_id or info.get("status") not in ("authorized", "captured") or \
            int(info.get("amount", 0)) != int(round(float(pay["amount"]) * 100)):
        db.run("UPDATE payments SET status='failed', error=? WHERE id=?", (f"gateway status {info.get('status')}", pay["id"]))
        raise ApiError(400, "Payment was not completed. Please try again.")
    return _finalize(pay["id"], rzp_payment_id, "Payment verified via Razorpay")


def complete_sandbox(user, payment_id, token, outcome):
    db = get_db()
    pay = db.one("SELECT p.*, o.user_id, o.id AS oid FROM payments p JOIN orders o ON o.id=p.order_id WHERE p.id=? AND p.method='sandbox'",
                 (payment_id,))
    if not pay or pay["user_id"] != user["id"]:
        raise ApiError(404, "Payment not found.")
    if pay["status"] != "created":
        raise ApiError(400, "This payment attempt has already been used. Start a new payment.")
    expected = sign(f"{pay['id']}:{pay['oid']}:{float(pay['amount']):.2f}:{pay['token_nonce']}")
    if not hmac.compare_digest(expected, token or ""):
        raise ApiError(400, "Invalid payment token.")
    if outcome != "success":
        db.run("UPDATE payments SET status='failed', error='declined (sandbox)' WHERE id=?", (pay["id"],))
        db.run("UPDATE orders SET payment_status='failed' WHERE id=? AND payment_status='pending'", (pay["order_id"],))
        from .orders import add_event
        add_event(db, pay["order_id"], "payment_pending", "Payment attempt failed — you can retry", None)
        return {"ok": False, "message": "Payment failed. Your order is saved; you can retry payment before it expires."}
    order = _finalize(pay["id"], f"sbx_pay_{secrets.token_hex(6)}", "Payment confirmed (sandbox test payment)")
    return {"ok": True, "order_no": order["order_no"]}


def _finalize(payment_row_id, provider_payment_id, note):
    db = get_db()
    with transaction(db):
        n = db.run("UPDATE payments SET status='verified', provider_payment_id=?, verified_at=? WHERE id=? AND status IN ('created','failed')",
                   (provider_payment_id, now_iso(), payment_row_id))
        pay = db.one("SELECT * FROM payments WHERE id=?", (payment_row_id,))
        order = db.one("SELECT * FROM orders WHERE id=?", (pay["order_id"],))
        if n == 1:
            order = mark_paid(db, order, note)
    if n == 1:
        notify(order["user_id"], f"Payment received for {order['order_no']}", f"₹{order['grand_total']} — thank you!",
               f"#/order/{order['order_no']}")
    return order


def handle_webhook(raw_body, signature):
    if not config.RAZORPAY_WEBHOOK_SECRET:
        raise ApiError(400, "Webhook secret not configured.")
    expected = hmac.new(config.RAZORPAY_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        raise ApiError(400, "Invalid webhook signature.")
    event = json.loads(raw_body)
    db = get_db()
    entity = event.get("payload", {}).get("payment", {}).get("entity", {})
    pay = db.one("SELECT * FROM payments WHERE provider_order_id=? AND method='razorpay'", (entity.get("order_id"),))
    if not pay:
        return {"ok": True, "ignored": True}
    if event.get("event") in ("payment.captured", "order.paid"):
        if int(entity.get("amount", 0)) == int(round(float(pay["amount"]) * 100)):
            _finalize(pay["id"], entity.get("id"), "Payment confirmed by Razorpay webhook")
    elif event.get("event") == "payment.failed":
        db.run("UPDATE payments SET status='failed', error=? WHERE id=? AND status='created'",
               ((entity.get("error_description") or "failed")[:200], pay["id"]))
    return {"ok": True}


def refund_via_gateway(order):
    """Attempt an automatic refund for Razorpay payments. Returns reference or None (manual refund)."""
    if order["payment_method"] != "razorpay" or not config.razorpay_configured():
        return None
    db = get_db()
    pay = db.one("SELECT * FROM payments WHERE order_id=? AND status='verified' AND method='razorpay'", (order["id"],))
    if not pay or not pay["provider_payment_id"]:
        return None
    r = _rzp_request("POST", f"/payments/{pay['provider_payment_id']}/refund",
                     {"amount": int(round(float(order["grand_total"]) * 100))})
    return r.get("id")


# ---------------------------------------------------------------- direct UPI (manual confirmation)
UTR_RE = __import__("re").compile(r"^[A-Za-z0-9]{10,35}$")


def upi_link(order, amount=None):
    from urllib.parse import quote
    s = get_settings()
    amount = float(order["grand_total"] if amount is None else amount)
    payee = (s.get("upi_payee_name") or s["store_name"])[:50]
    # Only the basic fields: merchant-only fields (tr, mc) make some apps refuse payments to personal UPI IDs
    parts = {"pa": s["upi_id"], "pn": payee, "am": f"{amount:.2f}", "cu": "INR", "tn": f"Order {order['order_no']}"}
    return "upi://pay?" + "&".join(f"{k}={quote(str(v), safe='@.')}" for k, v in parts.items())


def _start_upi(order, amount):
    db = get_db()
    s = get_settings()
    existing = db.one("SELECT id FROM payments WHERE order_id=? AND method='upi' AND status IN ('created','failed') ORDER BY id DESC LIMIT 1",
                      (order["id"],))
    if existing:
        db.run("UPDATE payments SET status='created', error=NULL, provider_payment_id=NULL WHERE id=?", (existing["id"],))
        pid = existing["id"]
    else:
        pid = db.insert("payments", {"order_id": order["id"], "method": "upi", "provider_order_id": f"UPI-{order['order_no']}",
                                     "amount": amount, "status": "created", "created_at": now_iso()})
    db.run("UPDATE orders SET payment_method='upi' WHERE id=?", (order["id"],))
    return {"method": "upi", "payment_id": pid, "upi_id": s["upi_id"], "payee": s.get("upi_payee_name") or s["store_name"],
            "amount": amount, "order_no": order["order_no"], "link": upi_link(order, amount),
            "expires_at": order["payment_expires_at"]}


def submit_upi(order, user, utr):
    """Customer reports the UPI transaction reference; the store confirms it by checking its bank/UPI app."""
    from .orders import add_event
    db = get_db()
    utr = (utr or "").strip().replace(" ", "")
    if order["payment_method"] != "upi":
        raise ApiError(400, "This order is not set to UPI payment.")
    if order["status"] != "payment_pending" or order["payment_status"] not in ("pending", "failed"):
        raise ApiError(400, "This order is not awaiting payment.")
    if not UTR_RE.match(utr):
        raise ApiError(400, "Enter the UPI transaction ID / UTR exactly as shown in your UPI app (usually 12 digits).")
    with transaction(db):
        dup = db.one("SELECT p.order_id FROM payments p WHERE p.method='upi' AND p.provider_payment_id=? AND p.status IN ('submitted','verified') "
                     "AND p.order_id<>?", (utr, order["id"]))
        if dup:
            raise ApiError(409, "This transaction ID has already been used for another order. Please check it.")
        pay = db.one("SELECT * FROM payments WHERE order_id=? AND method='upi' ORDER BY id DESC LIMIT 1", (order["id"],))
        if pay and pay["status"] == "submitted":
            raise ApiError(400, "You have already submitted a transaction ID. The store will confirm it shortly.")
        if not pay or pay["status"] not in ("created", "failed"):
            pid = db.insert("payments", {"order_id": order["id"], "method": "upi", "provider_order_id": f"UPI-{order['order_no']}",
                                         "amount": order["grand_total"], "status": "created", "created_at": now_iso()})
        else:
            pid = pay["id"]
        db.run("UPDATE payments SET status='submitted', provider_payment_id=?, error=NULL, created_at=? WHERE id=?", (utr, now_iso(), pid))
        # Stop the auto-cancel timer while the store checks the payment
        db.run("UPDATE orders SET payment_expires_at=NULL, payment_status='pending', updated_at=? WHERE id=?", (now_iso(), order["id"]))
        add_event(db, order["id"], "payment_pending", f"UPI payment submitted (Txn ID {utr}) — waiting for the store to confirm", user["id"])
    for staff in db.all("SELECT id FROM users WHERE role='owner' AND status='active'"):
        notify(staff["id"], f"UPI payment to confirm: {order['order_no']}",
               f"₹{order['grand_total']} · Txn ID {utr}. Check your UPI/bank app, then confirm or reject on the order page.",
               f"#/orders/{order['id']}", email=False)
    return db.one("SELECT * FROM orders WHERE id=?", (order["id"],))


def review_upi(order, staff, action, note=None):
    """Owner/staff confirm (after seeing the money in their account) or reject a submitted UPI payment."""
    from .orders import add_event
    db = get_db()
    s = get_settings()
    with transaction(db):
        pay = db.one("SELECT * FROM payments WHERE order_id=? AND method='upi' AND status='submitted' ORDER BY id DESC LIMIT 1",
                     (order["id"],))
        if not pay:
            raise ApiError(400, "There is no UPI payment waiting for confirmation on this order.")
        order = db.one("SELECT * FROM orders WHERE id=?", (order["id"],))
        if action == "confirm":
            db.run("UPDATE payments SET status='verified', verified_at=? WHERE id=?", (now_iso(), pay["id"]))
            order = mark_paid(db, order, f"UPI payment confirmed by the store (Txn ID {pay['provider_payment_id']})")
            msg = (f"Payment received for {order['order_no']}", f"₹{order['grand_total']} via UPI — thank you!")
        elif action == "reject":
            reason = (note or "").strip()[:200] or "The payment was not found in the store's account."
            from datetime import timedelta
            from ..db import iso, now_utc
            db.run("UPDATE payments SET status='failed', error=? WHERE id=?", (reason, pay["id"]))
            exp = iso(now_utc() + timedelta(minutes=int(s["payment_expiry_minutes"]))) if order["status"] == "payment_pending" else None
            db.run("UPDATE orders SET payment_status='failed', payment_expires_at=?, updated_at=? WHERE id=?", (exp, now_iso(), order["id"]))
            add_event(db, order["id"], "payment_pending", f"UPI payment could not be confirmed: {reason} Please check and submit the correct transaction ID, or pay again.",
                      staff["id"])
            order = db.one("SELECT * FROM orders WHERE id=?", (order["id"],))
            msg = (f"Payment not confirmed for {order['order_no']}", reason + " Open your order to fix it.")
        else:
            raise ApiError(400, "Unknown action.")
    notify(order["user_id"], msg[0], msg[1], f"#/order/{order['order_no']}")
    return order
