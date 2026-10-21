"""Item-level returns: a customer returns one or more items (not the whole order). The order itself stays 'Delivered';
stock, the refund and the vendor's earnings are adjusted for just those items."""
from ..db import get_db, now_iso, now_utc, parse_iso, transaction
from ..security import audit
from ..services import inventory
from ..services import orders as osvc
from ..services.common import get_settings, money, notify
from ..web import ApiError, api, num, text
from .vendor import sync_earnings

ACTIVE = ("requested", "approved", "received", "refunded")
LABEL = {"requested": "Waiting for the store", "approved": "Approved", "received": "Item received — refund in progress", "refunded": "Refunded", "rejected": "Not approved"}


def returnable_map(db, order_id):
    """{order_item_id: qty that can still be returned}"""
    used = {r["order_item_id"]: r["n"] for r in db.all("SELECT order_item_id, SUM(qty) AS n FROM item_returns WHERE order_id=? AND status<>'rejected' GROUP BY order_item_id", (order_id,))}
    return {i["id"]: max(0, i["qty"] - used.get(i["id"], 0)) for i in db.all("SELECT id, qty FROM order_items WHERE order_id=?", (order_id,))}


def can_return_items(db, order):
    if order["status"] != "delivered" or not order["delivered_at"]:
        return False
    if (now_utc() - parse_iso(order["delivered_at"])).days > int(get_settings()["return_window_days"]):
        return False
    if db.one("SELECT id FROM return_requests WHERE order_id=?", (order["id"],)):
        return False
    return any(v > 0 for v in returnable_map(db, order["id"]).values())


def item_returns_for_order(db, order_id):
    return db.all("SELECT r.id, r.order_item_id, i.name, r.qty, r.amount, r.reason, r.status, r.note, r.reference, r.created_at "
                  "FROM item_returns r JOIN order_items i ON i.id=r.order_item_id WHERE r.order_id=? ORDER BY r.id", (order_id,))


def has_active(db, order_id):
    return bool(db.one("SELECT id FROM item_returns WHERE order_id=? AND status<>'rejected'", (order_id,)))


def _vendor_users(db, product_id):
    return db.all("SELECT v.user_id FROM product_vendors pv JOIN vendors v ON v.id=pv.vendor_id WHERE pv.product_id=?", (product_id,))


# ---------------------------------------------------------------- customer
@api("POST", "/api/orders/{no}/item-returns", auth="customer")
def request_item_return(ctx):
    db = get_db()
    order = db.one("SELECT * FROM orders WHERE order_no=? AND user_id=?", (ctx.params["no"], ctx.uid))
    if not order:
        raise ApiError(404, "Order not found.")
    if not can_return_items(db, order):
        raise ApiError(400, "Items from this order can't be returned now (not delivered, window closed, or nothing left to return).")
    reason = text(ctx.get("reason"), "Reason", max_len=300, min_len=3)
    wanted = ctx.get("items")
    if not isinstance(wanted, list) or not wanted:
        raise ApiError(400, "Choose at least one item to return.")
    left = returnable_map(db, order["id"])
    items = {i["id"]: i for i in db.all("SELECT * FROM order_items WHERE order_id=?", (order["id"],))}
    sub = float(order["subtotal"] or 0)
    share = 1 - (float(order["coupon_discount"] or 0) / sub) if sub > 0 else 1
    made = []
    with transaction(db):
        seen = set()
        for w in wanted:
            iid, q = int(w.get("item_id", 0)), int(num(w.get("qty"), "Quantity", 0, 999, integer=True))
            if q == 0:
                continue
            if iid in seen or iid not in items:
                raise ApiError(400, "Invalid item selection.")
            seen.add(iid)
            if q > left.get(iid, 0):
                raise ApiError(400, f"You can return at most {left.get(iid, 0)} of “{items[iid]['name']}”.")
            it = items[iid]
            amount = money(float(it["unit_price"]) * q * share)
            rid = db.insert("item_returns", {"order_id": order["id"], "order_item_id": iid, "product_id": it["product_id"], "user_id": ctx.uid, "qty": q,
                                             "amount": amount, "reason": reason, "status": "requested", "created_at": now_iso()})
            made.append((rid, it, q))
        if not made:
            raise ApiError(400, "Choose at least one item to return.")
        osvc.add_event(db, order["id"], order["status"], "Return requested for: " + ", ".join(f"{it['name']} × {q}" for _, it, q in made), ctx.uid)
    summary = ", ".join(f"{it['name']} × {q}" for _, it, q in made)
    for ow in db.all("SELECT id FROM users WHERE role='owner' AND status='active'"):
        notify(ow["id"], f"Item return requested · {order['order_no']}", f"{summary}. Reason: {reason}", "/admin#/returns", email=True)
    for _, it, _q in made:
        for vu in _vendor_users(db, it["product_id"]):
            notify(vu["user_id"], f"Return requested · {order['order_no']}", f"A customer asked to return: {it['name']}. The store will decide.", None, email=False)
    return {"ok": True, "count": len(made)}


# ---------------------------------------------------------------- owner / staff
def _row(db, rid):
    r = db.one("SELECT r.*, o.order_no, o.payment_status, o.payment_method, o.user_id AS customer_id FROM item_returns r JOIN orders o ON o.id=r.order_id WHERE r.id=?", (rid,))
    if not r:
        raise ApiError(404, "Return not found.")
    return r


@api("GET", "/api/admin/item-returns", auth="admin", perm="returns")
def item_returns_list(ctx):
    db = get_db()
    flt = ctx.q("status", "open")
    where = {"open": "r.status IN ('requested','approved','received')", "all": "1=1"}.get(flt, "r.status=?")
    params = (flt,) if flt not in ("open", "all") else ()
    rows = db.all("SELECT r.*, i.name, o.order_no, o.payment_status, u.name AS customer, "
                  "(SELECT v.business_name FROM product_vendors pv JOIN vendors v ON v.id=pv.vendor_id WHERE pv.product_id=r.product_id) AS vendor "
                  "FROM item_returns r JOIN order_items i ON i.id=r.order_item_id JOIN orders o ON o.id=r.order_id JOIN users u ON u.id=r.user_id "
                  f"WHERE {where} ORDER BY r.id DESC LIMIT 200", params)
    for r in rows:
        r["label"] = LABEL.get(r["status"], r["status"])
    return {"items": rows}


@api("POST", "/api/admin/item-returns/{rid:int}/decide", auth="admin", perm="returns")
def item_return_decide(ctx):
    return _decide(ctx, _row(get_db(), ctx.params["rid"]), "the store")


def _decide(ctx, r, who):
    db = get_db()
    if r["status"] != "requested":
        raise ApiError(400, "This request was already decided.")
    action = ctx.get("action")
    if action not in ("approve", "reject"):
        raise ApiError(400, "Choose approve or reject.")
    note = text(ctx.get("note"), "Note", required=False, max_len=300)
    new = "approved" if action == "approve" else "rejected"
    db.run("UPDATE item_returns SET status=?, note=?, decided_at=? WHERE id=?", (new, note, now_iso(), r["id"]))
    name = db.val("SELECT name FROM order_items WHERE id=?", (r["order_item_id"],))
    notify(r["customer_id"], f"Order {r['order_no']}: return {'approved' if action == 'approve' else 'not approved'}",
           (f"Your return of {name} × {r['qty']} is approved. The store will contact you to collect it." if action == "approve" else f"Your return of {name} was not approved. {note or ''}").strip(),
           f"#/order/{r['order_no']}")
    audit(ctx.uid, "item_return_" + action, "order", r["order_id"], f"{name} (by {who})", ctx.ip)
    if who != "the store":
        for ow in db.all("SELECT id FROM users WHERE role='owner' AND status='active'"):
            notify(ow["id"], f"Vendor {action}d an item return · {r['order_no']}", f"{who} {action}d the return of {name} × {r['qty']}.", "/admin#/returns", email=False)
    return {"ok": True}


@api("POST", "/api/admin/item-returns/{rid:int}/receive", auth="admin", perm="returns")
def item_return_receive(ctx):
    return _receive(ctx, _row(get_db(), ctx.params["rid"]), "the store")


def _receive(ctx, r, who):
    db = get_db()
    if r["status"] != "approved":
        raise ApiError(400, "Approve the return first.")
    restock = bool(ctx.get("restock", True))
    with transaction(db):
        if r["product_id"]:
            inventory.restock_return(db, r["product_id"], r["qty"], r["order_id"], damaged=not restock, actor_id=ctx.uid,
                                     note="Customer item return" + ("" if restock else " (damaged)"))
        db.run("UPDATE item_returns SET status='received', restock=?, received_at=? WHERE id=?", (1 if restock else 0, now_iso(), r["id"]))
    audit(ctx.uid, "item_return_received", "order", r["order_id"], ("restocked" if restock else "damaged") + f" (by {who})", ctx.ip)
    if who != "the store":
        for ow in db.all("SELECT id FROM users WHERE role='owner' AND status='active'"):
            notify(ow["id"], f"Returned item received · {r['order_no']}", f"{who} received the returned item. Please send the refund and mark it refunded.", "/admin#/returns", email=True)
    return {"ok": True}


@api("POST", "/api/admin/item-returns/{rid:int}/refund", auth="admin", perm="returns")
def item_return_refund(ctx):
    db = get_db()
    r = _row(db, ctx.params["rid"])
    if r["status"] != "received":
        raise ApiError(400, "Mark the item as received first.")
    if r["payment_status"] != "paid":
        raise ApiError(400, "No payment has been received for this order (for cash on delivery, record the cash first), so there is nothing to refund.")
    t = now_iso()
    with transaction(db):
        db.insert("refunds", {"order_id": r["order_id"], "amount": r["amount"], "status": "completed", "method": r["payment_method"],
                              "reference": text(ctx.get("reference"), "Reference", required=False, max_len=80), "note": "Item return",
                              "created_at": t, "completed_at": t})
        db.run("UPDATE item_returns SET status='refunded', reference=?, refunded_at=? WHERE id=?", (text(ctx.get("reference"), "Reference", required=False, max_len=80), t, r["id"]))
        _vendor_adjust(db, r)
    name = db.val("SELECT name FROM order_items WHERE id=?", (r["order_item_id"],))
    notify(r["customer_id"], f"Order {r['order_no']}: refund done", f"₹{r['amount']:.2f} refunded for {name} × {r['qty']}.", f"#/order/{r['order_no']}")
    audit(ctx.uid, "item_return_refund", "order", r["order_id"], f"{r['amount']}", ctx.ip)
    return {"ok": True}


def _vendor_adjust(db, r):
    pv = db.one("SELECT vendor_id FROM product_vendors WHERE product_id=?", (r["product_id"],))
    if not pv:
        return
    sync_earnings(db, pv["vendor_id"])
    e = db.one("SELECT * FROM vendor_earnings WHERE order_item_id=?", (r["order_item_id"],))
    qty = db.val("SELECT qty FROM order_items WHERE id=?", (r["order_item_id"],))
    if not e or not qty:
        return
    f = r["qty"] / qty
    # earning not paid yet -> just reduce it (-1); already paid -> deduct from the vendor's next payout (NULL = pending)
    settled = -1 if not e["payout_id"] else None
    db.run("INSERT INTO vendor_adjustments(vendor_id, order_item_id, return_id, gross, commission, net, claw_payout_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
           (pv["vendor_id"], r["order_item_id"], r["id"], money(e["gross"] * f), money(e["commission"] * f), money(e["net"] * f), settled, now_iso()))


# ---------------------------------------------------------------- vendor (read only)
@api("GET", "/api/vendor/item-returns", auth="vendor")
def vendor_item_returns(ctx):
    db = get_db()
    v = db.one("SELECT id FROM vendors WHERE user_id=?", (ctx.uid,))
    if not v:
        raise ApiError(403, "No vendor profile is linked to this account.")
    rows = db.all("SELECT r.id, r.qty, r.amount, r.reason, r.status, r.created_at, i.name, o.order_no FROM item_returns r JOIN order_items i ON i.id=r.order_item_id "
                  "JOIN orders o ON o.id=r.order_id JOIN product_vendors pv ON pv.product_id=r.product_id WHERE pv.vendor_id=? ORDER BY r.id DESC LIMIT 100", (v["id"],))
    for r in rows:
        r["label"] = LABEL.get(r["status"], r["status"])
    return {"items": rows}


def _vendor_row(db, ctx):
    v = db.one("SELECT id, business_name FROM vendors WHERE user_id=?", (ctx.uid,))
    if not v:
        raise ApiError(403, "No vendor profile is linked to this account.")
    r = _row(db, ctx.params["rid"])
    mine = db.one("SELECT 1 AS x FROM product_vendors WHERE product_id=? AND vendor_id=?", (r["product_id"], v["id"]))
    if not mine:
        raise ApiError(404, "Return not found.")
    return r, v["business_name"]


@api("POST", "/api/vendor/item-returns/{rid:int}/decide", auth="vendor")
def vendor_item_return_decide(ctx):
    r, name = _vendor_row(get_db(), ctx)
    return _decide(ctx, r, name)


@api("POST", "/api/vendor/item-returns/{rid:int}/receive", auth="vendor")
def vendor_item_return_receive(ctx):
    r, name = _vendor_row(get_db(), ctx)
    return _receive(ctx, r, name)
