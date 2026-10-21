"""Orders: pricing quotes, placement (with atomic stock reservation), status workflow and timeline."""
import math
import secrets
from datetime import timedelta

from ..db import get_db, iso, jdump, jload, local_today, now_iso, now_utc, parse_iso, transaction
from ..web import ApiError
from . import inventory
from .common import available, get_settings, money, notify

STATUSES = [
    ("placed", "Order Placed"),
    ("payment_pending", "Payment Pending"),
    ("payment_confirmed", "Payment Confirmed"),
    ("confirmed", "Order Confirmed"),
    ("processing", "Processing"),
    ("packed", "Packed"),
    ("dispatched", "Dispatched"),
    ("in_transit", "In Transit"),
    ("out_for_delivery", "Out for Delivery"),
    ("delivered", "Delivered"),
    ("cancel_requested", "Cancellation Requested"),
    ("cancelled", "Cancelled"),
    ("return_requested", "Return Requested"),
    ("return_in_progress", "Return in Progress"),
    ("returned", "Returned"),
    ("refund_processing", "Refund Processing"),
    ("refunded", "Refunded"),
    ("delivery_failed", "Delivery Failed"),
]
STATUS_LABEL = dict(STATUSES)

# Allowed manual transitions from the admin panel. payment_confirmed is never set manually:
# only a verified payment (gateway signature / webhook / cash collection) may set it.
TRANSITIONS = {
    "placed": ["confirmed", "processing", "cancelled"],
    "payment_pending": ["cancelled"],
    "payment_confirmed": ["confirmed", "processing", "cancelled"],
    "confirmed": ["processing", "packed", "cancelled"],
    "processing": ["packed", "cancelled"],
    "packed": ["dispatched", "cancelled"],
    "dispatched": ["in_transit", "out_for_delivery", "delivered", "delivery_failed"],
    "in_transit": ["out_for_delivery", "delivered", "delivery_failed"],
    "out_for_delivery": ["delivered", "delivery_failed"],
    "delivery_failed": ["out_for_delivery", "in_transit", "cancelled"],
    "delivered": ["return_requested"],
    "cancel_requested": ["cancelled"],  # reject handled via returns queue
    "cancelled": ["refund_processing"],
    "return_requested": ["return_in_progress"],
    "return_in_progress": ["returned"],
    "returned": ["refund_processing"],
    "refund_processing": ["refunded"],
    "refunded": [],
}
SHIPPED = {"dispatched", "in_transit", "out_for_delivery", "delivered", "delivery_failed",
           "return_requested", "return_in_progress", "returned"}
ONLINE_METHODS = ("razorpay", "sandbox", "upi")
OPEN_STATUSES = {"placed", "payment_pending", "payment_confirmed", "confirmed", "processing", "packed",
                 "dispatched", "in_transit", "out_for_delivery", "cancel_requested", "delivery_failed"}
# Orders that count as real sales (excludes unpaid online orders and cancellations)
SALE_EXCLUDED = ("payment_pending", "cancelled", "returned", "refund_processing", "refunded")
CUSTOMER_CANCEL_DIRECT = {"placed", "payment_pending", "payment_confirmed", "confirmed", "processing"}
CUSTOMER_CANCEL_REQUEST = {"packed"}

TIMELINE_FLOW = ["placed", "confirmed", "packed", "dispatched", "out_for_delivery", "delivered"]
FLOW_LABEL = {"placed": "Placed", "confirmed": "Confirmed", "packed": "Packed", "dispatched": "Shipped", "out_for_delivery": "Out for delivery", "delivered": "Delivered"}


# ---------------------------------------------------------------- quote
def build_quote(user_id, delivery_code=None, coupon_code=None, payment_method=None, items=None):
    """Price the cart from the database (never trust client prices). Returns quote + any stock problems."""
    db = get_db()
    s = get_settings()
    if items is None:
        items = db.all("SELECT c.product_id, c.qty FROM cart_items c WHERE c.user_id=? ORDER BY c.id", (user_id,))
    lines, problems = [], []
    subtotal = mrp_total = tax_total = cost_total = 0.0
    for it in items:
        p = db.one("SELECT * FROM products WHERE id=?", (it["product_id"],))
        if not p or p["status"] not in ("active", "out_of_stock"):
            problems.append({"product_id": it["product_id"], "message": "This product is no longer available."})
            continue
        qty = int(it["qty"])
        avail = available(p) if p["status"] == "active" else 0
        max_q = min(p["max_per_order"] or s["max_qty_per_order"], s["max_qty_per_order"])
        if avail <= 0:
            problems.append({"product_id": p["id"], "message": f"{p['name']} is out of stock."})
        elif qty > avail:
            problems.append({"product_id": p["id"], "message": f"Only {avail} unit(s) of {p['name']} available."})
        elif qty > max_q:
            problems.append({"product_id": p["id"], "message": f"Maximum {max_q} units of {p['name']} per order."})
        price = money(p["selling_price"])
        mrp = money(p["mrp"] or p["selling_price"])
        line = money(price * qty)
        rate = float(p["tax_rate"] or 0)
        # prices are tax-inclusive: tax component = line * rate / (100 + rate)
        tax = money(line * rate / (100 + rate)) if s["prices_include_tax"] else money(line * rate / 100)
        subtotal += line
        mrp_total += mrp * qty
        tax_total += tax
        cost_total += float(p["cost_price"] or 0) * qty
        lines.append({"product_id": p["id"], "name": p["name"], "sku": p["sku"], "qty": qty, "unit_price": price,
                      "mrp": mrp, "line_total": line, "tax_rate": rate, "tax": tax, "available": avail,
                      "cost_price": money(p["cost_price"]), "slug": p["slug"]})

    # delivery
    methods = db.all("SELECT * FROM delivery_methods WHERE active=1 ORDER BY sort, id")
    method = next((m for m in methods if m["code"] == delivery_code), methods[0] if methods else None)
    delivery_charge = 0.0
    eta = None
    if method:
        delivery_charge = money(method["charge"])
        if method["free_above"] is not None and subtotal >= float(method["free_above"]):
            delivery_charge = 0.0
        today = local_today()
        eta = [str(today + timedelta(days=method["eta_min_days"])), str(today + timedelta(days=method["eta_max_days"]))]

    # coupon
    coupon_discount, coupon_msg, coupon_applied = 0.0, None, None
    if coupon_code:
        c = db.one("SELECT * FROM coupons WHERE UPPER(code)=UPPER(?)", (coupon_code.strip(),))
        now = now_iso()
        if not c or not c["active"]:
            coupon_msg = "Coupon code is not valid."
        elif c["starts_at"] and now < c["starts_at"] or c["ends_at"] and now > c["ends_at"]:
            coupon_msg = "Coupon has expired or is not active yet."
        elif c["usage_limit"] is not None and c["used_count"] >= c["usage_limit"]:
            coupon_msg = "Coupon usage limit reached."
        elif subtotal < float(c["min_order"] or 0):
            coupon_msg = f"Add items worth ₹{money(float(c['min_order']) - subtotal)} more to use this coupon."
        else:
            d = subtotal * float(c["value"]) / 100 if c["kind"] == "pct" else float(c["value"])
            if c["max_discount"]:
                d = min(d, float(c["max_discount"]))
            coupon_discount = money(min(d, subtotal))
            coupon_applied = c["code"]
            coupon_msg = f"{c['code']} applied."
    if coupon_discount and subtotal:
        tax_total = tax_total * (subtotal - coupon_discount) / subtotal

    grand = money(subtotal - coupon_discount + delivery_charge)
    pm_ok, pm_msg = payment_method_allowed(payment_method, grand) if payment_method else (True, None)
    return {
        "lines": lines, "problems": problems, "subtotal": money(subtotal), "mrp_total": money(mrp_total),
        "savings": money(mrp_total - subtotal + coupon_discount), "coupon": coupon_applied,
        "coupon_message": coupon_msg, "coupon_discount": coupon_discount,
        "delivery_method": method["code"] if method else None, "delivery_charge": delivery_charge,
        "delivery_methods": [{"code": m["code"], "name": m["name"], "description": m["description"],
                              "charge": money(m["charge"]), "free_above": m["free_above"],
                              "eta": [m["eta_min_days"], m["eta_max_days"]]} for m in methods],
        "eta": eta, "tax_total": money(tax_total), "tax_note": "incl. GST" if s["prices_include_tax"] else "GST extra",
        "grand_total": grand, "cost_total": money(cost_total),
        "payment_ok": pm_ok, "payment_message": pm_msg,
    }


def payment_method_allowed(method, amount):
    from .. import config
    s = get_settings()
    if method == "cod":
        if not s["cod_enabled"]:
            return False, "Cash on Delivery is currently disabled."
        if amount > float(s["cod_max_amount"] or 0):
            return False, f"Cash on Delivery is available for orders up to ₹{s['cod_max_amount']}."
        return True, None
    if method == "razorpay":
        if not (s["razorpay_enabled"] and config.razorpay_configured()):
            return False, "Online payment (Razorpay) is not configured yet."
        return True, None
    if method == "sandbox":
        if not s["sandbox_enabled"]:
            return False, "Test payments are disabled."
        return True, None
    if method == "upi":
        if not (s.get("upi_enabled") and s.get("upi_id")):
            return False, "UPI payment is not available right now."
        return True, None
    return False, "Choose a payment method."


# ---------------------------------------------------------------- place order
def _order_no(db):
    for _ in range(10):
        no = f"NC{local_today().strftime('%y%m%d')}{secrets.randbelow(900000) + 100000}"
        if not db.one("SELECT id FROM orders WHERE order_no=?", (no,)):
            return no
    raise ApiError(500, "Could not allocate order number.")


def place_order(user, address_id, delivery_code, payment_method, coupon_code, expected_total):
    db = get_db()
    s = get_settings()
    addr = db.one("SELECT * FROM addresses WHERE id=? AND user_id=?", (address_id, user["id"]))
    if not addr:
        raise ApiError(400, "Please choose a delivery address.")

    with transaction(db):
        quote = build_quote(user["id"], delivery_code, coupon_code, payment_method)
        if not quote["lines"]:
            raise ApiError(400, "Your cart is empty.")
        if quote["problems"]:
            raise ApiError(409, "Some items in your cart need attention.", {"quote": quote})
        if expected_total is not None and abs(float(expected_total) - quote["grand_total"]) > 0.009:
            raise ApiError(409, "Prices changed since you opened checkout. Please review the updated total.",
                           {"quote": quote})
        if coupon_code and not quote["coupon"]:
            raise ApiError(400, quote["coupon_message"] or "Coupon is not valid.")
        ok, msg = payment_method_allowed(payment_method, quote["grand_total"])
        if not ok:
            raise ApiError(400, msg)

        buyer = None
        if user.get("buyer_id"):
            buyer = db.one("SELECT * FROM buyers WHERE id=? AND active=1", (user["buyer_id"],))
        t = now_iso()
        online = payment_method in ONLINE_METHODS
        status = "payment_pending" if online else "placed"
        order_id = db.insert("orders", {
            "order_no": _order_no(db), "user_id": user["id"],
            "buyer_code": buyer["code"] if buyer else None,
            "buyer_company": buyer["company_code"] if buyer else None,
            "buyer_category": buyer["category_code"] if buyer else None,
            "status": status, "payment_method": payment_method,
            "payment_status": "pending",
            "mrp_total": quote["mrp_total"], "subtotal": quote["subtotal"], "coupon_code": quote["coupon"],
            "coupon_discount": quote["coupon_discount"], "delivery_method": quote["delivery_method"],
            "delivery_charge": quote["delivery_charge"], "tax_total": quote["tax_total"],
            "grand_total": quote["grand_total"], "cost_total": quote["cost_total"],
            "ship_name": addr["name"], "ship_phone": addr["phone"],
            "ship_address": jdump({k: addr[k] for k in ("line1", "line2", "city", "state", "pincode")}),
            "est_delivery_from": quote["eta"][0] if quote["eta"] else None,
            "est_delivery_to": quote["eta"][1] if quote["eta"] else None,
            "stock_state": "reserved", "created_at": t, "updated_at": t,
            "payment_expires_at": iso(now_utc() + timedelta(minutes=int(s["payment_expiry_minutes"]))) if online else None,
        })
        for ln in quote["lines"]:
            # Atomic reservation: fails if another customer took the stock a moment ago
            if not inventory.reserve(db, ln["product_id"], ln["qty"], order_id):
                p = db.one("SELECT * FROM products WHERE id=?", (ln["product_id"],))
                left = available(p) if p else 0
                raise ApiError(409, f"Sorry, only {left} unit(s) of {ln['name']} are left. Please update your cart.",
                               {"quote": build_quote(user["id"], delivery_code, coupon_code, payment_method)})
            db.insert("order_items", {
                "order_id": order_id, "product_id": ln["product_id"], "name": ln["name"], "sku": ln["sku"],
                "unit_price": ln["unit_price"], "mrp": ln["mrp"], "cost_price": ln["cost_price"],
                "tax_rate": ln["tax_rate"], "qty": ln["qty"], "line_total": ln["line_total"],
            })
        if quote["coupon"]:
            n = db.run("UPDATE coupons SET used_count=used_count+1 WHERE code=? AND (usage_limit IS NULL OR used_count < usage_limit)",
                       (quote["coupon"],))
            if n != 1:
                raise ApiError(409, "Coupon usage limit reached.")
        add_event(db, order_id, "placed", "Order placed" + (" — awaiting online payment" if online else " — Cash on Delivery"),
                  user["id"])
        if online:
            add_event(db, order_id, "payment_pending", "Waiting for payment confirmation", None)
        db.run("DELETE FROM cart_items WHERE user_id=?", (user["id"],))
        order = db.one("SELECT * FROM orders WHERE id=?", (order_id,))
    notify(user["id"], f"Order {order['order_no']} placed",
           f"Total ₹{order['grand_total']}. " + ("Complete payment to confirm your order." if online else "Pay cash on delivery."),
           f"#/order/{order['order_no']}")
    return order


# ---------------------------------------------------------------- status workflow
def add_event(db, order_id, status, note=None, actor_id=None, visible=True, at=None):
    db.insert("order_events", {"order_id": order_id, "status": status, "note": note, "actor_id": actor_id,
                               "visible": 1 if visible else 0, "created_at": at or now_iso()})


def _items(db, order_id):
    return db.all("SELECT * FROM order_items WHERE order_id=?", (order_id,))


def _apply_stock(db, order, new_status, actor_id, restock=True, at=None):
    """Keep stock in step with the order lifecycle."""
    state = order["stock_state"]
    items = [i for i in _items(db, order["id"]) if i["product_id"]]
    if new_status in SHIPPED - {"return_requested", "return_in_progress", "returned"} and state == "reserved":
        for i in items:
            inventory.commit_sale(db, i["product_id"], i["qty"], order["id"], actor_id, at)
        return "committed"
    if new_status == "cancelled":
        if state == "reserved":
            for i in items:
                inventory.release(db, i["product_id"], i["qty"], order["id"], "Order cancelled", actor_id, at)
            return "released"
        if state == "committed":  # cancelled after dispatch (e.g. failed delivery returned to store)
            for i in items:
                inventory.restock_return(db, i["product_id"], i["qty"], order["id"], False, actor_id, "Undelivered — back to store", at)
            return "returned"
    if new_status == "returned" and state == "committed":
        for i in items:
            inventory.restock_return(db, i["product_id"], i["qty"], order["id"], damaged=not restock, actor_id=actor_id, at=at)
        return "returned"
    return state


def change_status(order_id, new_status, actor, note=None, restock=True, system=False, at=None):
    """Move an order to a new status, enforcing the allowed workflow and updating stock/payments."""
    db = get_db()
    with transaction(db):
        order = db.one("SELECT * FROM orders WHERE id=?", (order_id,))
        if not order:
            raise ApiError(404, "Order not found.")
        cur = order["status"]
        if new_status not in STATUS_LABEL:
            raise ApiError(400, "Unknown status.")
        if not system and new_status not in TRANSITIONS.get(cur, []):
            raise ApiError(400, f"Cannot move an order from '{STATUS_LABEL[cur]}' to '{STATUS_LABEL[new_status]}'.")
        if new_status in ("return_requested", "return_in_progress", "returned") and cur != new_status and _has_item_returns(order_id):
            raise ApiError(400, "This order has item returns in progress, so it can't be returned as a whole.")
        if new_status == "refund_processing" and order["payment_status"] not in ("paid",):
            raise ApiError(400, "No payment has been received for this order, so there is nothing to refund.")
        if new_status in ("confirmed", "processing", "packed") and cur == "placed" and order["payment_method"] != "cod":
            raise ApiError(400, "Online orders can only proceed after payment is verified.")

        t = at or now_iso()
        updates = {"status": new_status, "updated_at": t}
        updates["stock_state"] = _apply_stock(db, order, new_status, actor["id"] if actor else None, restock, t)
        if new_status == "dispatched":
            updates["dispatched_at"] = t
        if new_status == "delivered":
            updates["delivered_at"] = t
        if new_status == "cancelled":
            updates["cancel_reason"] = note or order["cancel_reason"]
            if order["payment_status"] == "pending":
                updates["payment_status"] = "cancelled"
            if order["payment_status"] == "paid":
                # Paid & cancelled orders go straight into refund processing
                db.update("orders", order_id, updates)
                add_event(db, order_id, "cancelled", note, actor["id"] if actor else None, at=t)
                _start_refund(db, order, t)
                updates = {"status": "refund_processing", "updated_at": t}
                new_status = "refund_processing"
        if new_status == "refund_processing" and cur != "cancelled" and order["payment_status"] == "paid":
            _start_refund(db, order, t)
        if new_status == "refunded":
            db.run("UPDATE refunds SET status='completed', completed_at=? WHERE order_id=? AND status='processing'", (t, order_id))
            updates["payment_status"] = "refunded"
        if new_status == "returned" and order["payment_status"] != "paid":
            pass
        db.update("orders", order_id, updates)
        add_event(db, order_id, new_status, note, actor["id"] if actor else None, at=t)
        order = db.one("SELECT * FROM orders WHERE id=?", (order_id,))
    if not at:
        notify(order["user_id"], f"Order {order['order_no']}: {STATUS_LABEL[order['status']]}",
               note or f"Your order is now '{STATUS_LABEL[order['status']]}'.", f"#/order/{order['order_no']}")
    return order


def _start_refund(db, order, t):
    if not db.one("SELECT id FROM refunds WHERE order_id=? AND status='processing'", (order["id"],)):
        db.insert("refunds", {"order_id": order["id"], "amount": order["grand_total"], "status": "processing",
                              "method": order["payment_method"], "created_at": t})


def mark_paid(db, order, method_note, at=None):
    """Called only after a payment has been verified (signature/webhook/cash collection)."""
    t = at or now_iso()
    if order["payment_status"] == "paid":
        return order
    if order["status"] == "payment_pending":
        db.update("orders", order["id"], {"payment_status": "paid", "paid_at": t, "status": "payment_confirmed",
                                          "updated_at": t, "payment_expires_at": None})
        add_event(db, order["id"], "payment_confirmed", method_note, None, at=t)
    elif order["status"] == "cancelled":
        # Payment arrived after the order expired: record it and refund automatically
        db.update("orders", order["id"], {"payment_status": "paid", "paid_at": t, "updated_at": t})
        add_event(db, order["id"], "cancelled", "Payment received after order expired — refund initiated", None, at=t)
        _start_refund(db, order, t)
        db.update("orders", order["id"], {"status": "refund_processing"})
    else:
        db.update("orders", order["id"], {"payment_status": "paid", "paid_at": t, "updated_at": t})
        add_event(db, order["id"], order["status"], method_note, None, visible=True, at=t)
    return db.one("SELECT * FROM orders WHERE id=?", (order["id"],))


def expire_stale_payments():
    """Cancel online orders whose payment window has passed, releasing reserved stock."""
    db = get_db()
    rows = db.all("SELECT id FROM orders WHERE status='payment_pending' AND payment_expires_at IS NOT NULL AND payment_expires_at < ?",
                  (now_iso(),))
    for r in rows:
        try:
            change_status(r["id"], "cancelled", None, "Payment not completed in time — order cancelled and stock released", system=True)
            db.run("UPDATE payments SET status='expired' WHERE order_id=? AND status='created'", (r["id"],))
        except ApiError:
            pass
    return len(rows)


# ---------------------------------------------------------------- customer actions
def customer_cancel(order, user, reason):
    db = get_db()
    if order["status"] in CUSTOMER_CANCEL_DIRECT:
        return change_status(order["id"], "cancelled", user, f"Cancelled by customer: {reason}", system=True)
    if order["status"] in CUSTOMER_CANCEL_REQUEST:
        with transaction(db):
            db.insert("return_requests", {"order_id": order["id"], "user_id": user["id"], "kind": "cancel",
                                          "reason": reason, "status": "pending", "prev_status": order["status"],
                                          "created_at": now_iso()})
        return change_status(order["id"], "cancel_requested", user, f"Cancellation requested: {reason}", system=True)
    raise ApiError(400, "This order can no longer be cancelled. You can request a return after delivery.")


def customer_return(order, user, reason):
    db = get_db()
    s = get_settings()
    if order["status"] != "delivered" or not order["delivered_at"]:
        raise ApiError(400, "Returns can be requested only for delivered orders.")
    days = (now_utc() - parse_iso(order["delivered_at"])).days
    if days > int(s["return_window_days"]):
        raise ApiError(400, f"The {s['return_window_days']}-day return window for this order has closed.")
    if _has_item_returns(order["id"]):
        raise ApiError(400, "This order already has item returns, so it can't be returned as a whole.")
    with transaction(db):
        db.insert("return_requests", {"order_id": order["id"], "user_id": user["id"], "kind": "return",
                                      "reason": reason, "status": "pending", "prev_status": "delivered",
                                      "created_at": now_iso()})
    return change_status(order["id"], "return_requested", user, f"Return requested: {reason}", system=True)


def _has_item_returns(order_id):
    return bool(get_db().one("SELECT id FROM item_returns WHERE order_id=? AND status<>'rejected'", (order_id,)))


def order_actions(order):
    s = get_settings()
    can_return = False
    if order["status"] == "delivered" and order["delivered_at"]:
        can_return = (now_utc() - parse_iso(order["delivered_at"])).days <= int(s["return_window_days"])
    return {
        "can_cancel": order["status"] in CUSTOMER_CANCEL_DIRECT | CUSTOMER_CANCEL_REQUEST,
        "cancel_needs_approval": order["status"] in CUSTOMER_CANCEL_REQUEST,
        "can_return": can_return and not _has_item_returns(order["id"]),
        "can_pay": order["status"] == "payment_pending" and order["payment_status"] in ("pending", "failed")
                   and not _upi_submitted(order),
    }


def _upi_submitted(order):
    if order["payment_method"] != "upi":
        return False
    return bool(get_db().one("SELECT id FROM payments WHERE order_id=? AND method='upi' AND status='submitted'", (order["id"],)))


def timeline(db, order, include_hidden=False):
    events = db.all("SELECT e.*, u.name AS actor_name, u.role AS actor_role FROM order_events e "
                    "LEFT JOIN users u ON u.id=e.actor_id WHERE e.order_id=? ORDER BY e.created_at, e.id", (order["id"],))
    out = []
    for e in events:
        if not include_hidden and not e["visible"]:
            continue
        item = {"status": e["status"], "label": STATUS_LABEL.get(e["status"], e["status"]), "note": e["note"],
                "at": e["created_at"]}
        if include_hidden:
            item["actor"] = e["actor_name"] or "System"
        out.append(item)
    # progress steps for the tracker
    reached = {e["status"] for e in events}
    flow = []
    for st in TIMELINE_FLOW:
        hit = st in reached or (st == "confirmed" and "payment_confirmed" in reached and order["status"] not in ("payment_pending",))
        flow.append({"status": st, "label": FLOW_LABEL[st], "done": hit})
    # anything after the last reached step counts as done if a later one is reached
    last = max((i for i, f in enumerate(flow) if f["done"]), default=-1)
    for i in range(last + 1):
        flow[i]["done"] = True
    return out, flow


def serialize_order(db, order, admin=False):
    items = _items(db, order["id"])
    from .common import first_images
    imgs = first_images([i["product_id"] for i in items if i["product_id"]])
    events, flow = timeline(db, order, include_hidden=admin)
    out = {k: order[k] for k in order.keys() if admin or k not in ("cost_total", "is_sample")}
    out["ship_address"] = jload(order["ship_address"], {})
    out["status_label"] = STATUS_LABEL.get(order["status"], order["status"])
    out["items"] = [{**{k: i[k] for k in i.keys() if admin or k != "cost_price"},
                     "image": imgs.get(i["product_id"], "/static/common/placeholder.svg")} for i in items]
    vmap = {r["product_id"]: r for r in db.all("SELECT pv.product_id, v.id AS vendor_id, v.business_name FROM product_vendors pv JOIN vendors v ON v.id=pv.vendor_id "
                                               "WHERE pv.product_id IN (SELECT product_id FROM order_items WHERE order_id=?)", (order["id"],))}
    for it in out["items"]:
        vr = vmap.get(it.get("product_id"))
        it["vendor"] = vr["business_name"] if vr else None
        it["vendor_id"] = vr["vendor_id"] if vr else None
    out["shipments"] = []
    for f in db.all("SELECT f.vendor_id, v.business_name AS vendor, f.status, f.courier, f.tracking_no FROM vendor_fulfillment f JOIN vendors v ON v.id=f.vendor_id WHERE f.order_id=?", (order["id"],)):
        out["shipments"].append({"vendor": f["vendor"], "vendor_id": f["vendor_id"], "status": f["status"], "courier": f["courier"], "tracking_no": f["tracking_no"],
                                 "items": [f"{i['name']} × {i['qty']}" for i in out["items"] if i.get("vendor_id") == f["vendor_id"]]})
    from ..routes import item_returns as _ir
    rm = _ir.returnable_map(db, order["id"])
    for it in out["items"]:
        it["returnable"] = rm.get(it["id"], 0)
    out["item_returns"] = _ir.item_returns_for_order(db, order["id"])
    if admin:
        out["vendor_parts"] = db.all("SELECT v.business_name AS vendor, f.status, f.courier, f.tracking_no FROM vendor_fulfillment f JOIN vendors v ON v.id=f.vendor_id WHERE f.order_id=?", (order["id"],))
    out["timeline"] = events
    out["progress"] = flow
    out["refunds"] = db.all("SELECT amount, status, method, reference, created_at, completed_at FROM refunds WHERE order_id=?",
                            (order["id"],))
    out["requests"] = db.all("SELECT id, kind, reason, status, resolution_note, created_at, resolved_at FROM return_requests "
                             "WHERE order_id=? ORDER BY id", (order["id"],))
    out["actions"] = order_actions(order)
    out["actions"]["can_return_items"] = _ir.can_return_items(db, order)
    if order["payment_method"] == "upi":
        p = db.one("SELECT provider_payment_id AS utr, status, error, created_at FROM payments WHERE order_id=? AND method='upi' "
                   "ORDER BY id DESC LIMIT 1", (order["id"],))
        out["upi"] = p
    return out


def ceil_int(x):
    return int(math.ceil(x))
