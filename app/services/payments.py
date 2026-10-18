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
    if method not in ("razorpay", "sandbox"):
        raise ApiError(400, "Choose an online payment method.")
    ok, msg = payment_method_allowed(method, order["grand_total"])
    if not ok:
        raise ApiError(400, msg)
    amount = float(order["grand_total"])
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
