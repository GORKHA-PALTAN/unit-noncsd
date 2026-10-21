"""Vendors: owner manages vendor accounts and approves their products; vendors manage only their own products.

Safety rule: a product with no row in product_vendors belongs to the shop owner exactly as before.
Vendor products stay hidden from the store (status 'draft') until the owner approves them.
"""
import csv
import io
from datetime import date, timedelta

from starlette.responses import Response

from ..db import get_db, jload, local_date, local_day_start_utc, local_today, now_iso, now_utc, parse_iso, transaction
from ..security import audit, destroy_user_sessions, hash_password, password_problem
from ..services import inventory
from ..services import orders as osvc
from .. import config
from ..services.common import vendor_map, delete_file, first_images, get_settings, money, notify, product_card, save_file, unique_slug
from ..web import ApiError, api, num, text
from .admin import _product_fields, _product_out, _sniff, upload_images
from .auth import EMAIL_RE

CONTENT_FIELDS = ("name", "description", "category_id")


# ================================================================ owner: manage vendors
def _vendor_row(db, v):
    out = dict(v)
    out["products"] = db.val("SELECT COUNT(*) FROM product_vendors WHERE vendor_id=?", (v["id"],))
    out["due_now"] = ledger(db, v["id"])[0]["due_now"]
    out["live"] = db.val("SELECT COUNT(*) FROM product_vendors pv JOIN products p ON p.id=pv.product_id "
                         "WHERE pv.vendor_id=? AND pv.approval='approved' AND p.status='active'", (v["id"],))
    out["pending"] = db.val("SELECT COUNT(*) FROM product_vendors WHERE vendor_id=? AND approval='pending'", (v["id"],))
    return out


@api("GET", "/api/admin/vendors", auth="owner")
def vendors_list(ctx):
    db = get_db()
    rows = db.all("SELECT v.*, u.email, u.status AS user_status, u.last_login_at FROM vendors v JOIN users u ON u.id=v.user_id ORDER BY v.id DESC")
    return {"items": [_vendor_row(db, v) for v in rows],
            "pending_products": db.val("SELECT COUNT(*) FROM product_vendors WHERE approval='pending'")}


def _vendor_fields(ctx):
    pct = num(ctx.get("commission_pct", 10), "Commission %", 0, 90)
    return {
        "business_name": text(ctx.get("business_name"), "Business name", max_len=100, min_len=2),
        "contact_name": text(ctx.get("contact_name"), "Contact name", max_len=80, min_len=2),
        "phone": text(ctx.get("phone"), "Phone", required=False, max_len=16),
        "address": text(ctx.get("address"), "Address", required=False, max_len=300),
        "gst_no": text(ctx.get("gst_no"), "GST number", required=False, max_len=20),
        "bank_holder": text(ctx.get("bank_holder"), "Account holder", required=False, max_len=80),
        "bank_account": text(ctx.get("bank_account"), "Bank account number", required=False, max_len=30),
        "bank_ifsc": text(ctx.get("bank_ifsc"), "IFSC", required=False, max_len=15),
        "upi": text(ctx.get("upi"), "UPI ID", required=False, max_len=60),
        "commission_pct": pct,
    }


@api("POST", "/api/admin/vendors", auth="owner")
def vendor_create(ctx):
    db = get_db()
    email = text(ctx.get("email"), "Email", max_len=120).lower()
    if not EMAIL_RE.match(email):
        raise ApiError(400, "Enter a valid email.")
    if db.one("SELECT id FROM users WHERE email=?", (email,)):
        raise ApiError(409, "An account with this email already exists.")
    pw = ctx.get("password")
    prob = password_problem(pw)
    if prob:
        raise ApiError(400, prob)
    d = _vendor_fields(ctx)
    with transaction(db):
        uid = db.insert("users", {"name": d["contact_name"], "email": email, "phone": d["phone"], "password_hash": hash_password(pw),
                                  "role": "vendor", "permissions": "[]", "status": "active", "created_at": now_iso()})
        d.update({"user_id": uid, "created_at": now_iso()})
        vid = db.insert("vendors", d)
        audit(ctx.uid, "vendor_create", "vendor", vid, d["business_name"], ctx.ip)
    vendor_map(force=True)
    return {"ok": True, "id": vid}


@api("PUT", "/api/admin/vendors/{vid:int}", auth="owner")
def vendor_update(ctx):
    db = get_db()
    v = db.one("SELECT * FROM vendors WHERE id=?", (ctx.params["vid"],))
    if not v:
        raise ApiError(404, "Vendor not found.")
    d = _vendor_fields(ctx)
    st = ctx.get("status", "active")
    if st not in ("active", "suspended"):
        raise ApiError(400, "Invalid status.")
    u = {"name": d["contact_name"], "phone": d["phone"], "status": st}
    if ctx.get("password"):
        prob = password_problem(ctx.get("password"))
        if prob:
            raise ApiError(400, prob)
        u["password_hash"] = hash_password(ctx.get("password"))
    with transaction(db):
        db.update("vendors", v["id"], d)
        db.update("users", v["user_id"], u)
        if st == "suspended":  # hide every live product of a suspended vendor; the owner re-approves later
            db.run("UPDATE products SET status='draft', updated_at=? WHERE status IN ('active','out_of_stock') AND id IN "
                   "(SELECT product_id FROM product_vendors WHERE vendor_id=?)", (now_iso(), v["id"]))
            db.run("UPDATE product_vendors SET approval='pending', updated_at=? WHERE vendor_id=? AND approval='approved'", (now_iso(), v["id"]))
    if st == "suspended" or ctx.get("password"):
        destroy_user_sessions(v["user_id"])
    audit(ctx.uid, "vendor_update", "vendor", v["id"], f"{d['business_name']} ({st})", ctx.ip)
    vendor_map(force=True)
    return {"ok": True}


@api("GET", "/api/admin/vendor-products", auth="owner")
def vendor_products_admin(ctx):
    db = get_db()
    where, params = ["1=1"], []
    ap = ctx.q("approval")
    if ap in ("pending", "approved", "rejected"):
        where.append("pv.approval=?"); params.append(ap)
    if ctx.q("vendor"):
        where.append("pv.vendor_id=?"); params.append(int(ctx.q("vendor")))
    rows = db.all("SELECT p.*, pv.approval, pv.note, v.business_name AS vendor, v.id AS vendor_id, c.name AS category "
                  "FROM product_vendors pv JOIN products p ON p.id=pv.product_id JOIN vendors v ON v.id=pv.vendor_id "
                  "LEFT JOIN categories c ON c.id=p.category_id WHERE " + " AND ".join(where) +
                  " ORDER BY CASE pv.approval WHEN 'pending' THEN 0 ELSE 1 END, p.updated_at DESC LIMIT 300", params)
    imgs = first_images([r["id"] for r in rows])
    items = []
    for r in rows:
        items.append({"id": r["id"], "name": r["name"], "description": r["description"], "category": r["category"], "brand": r["brand"],
                      "price": r["selling_price"], "mrp": r["mrp"], "stock": r["physical_stock"], "status": r["status"],
                      "approval": r["approval"], "note": r["note"], "vendor": r["vendor"], "vendor_id": r["vendor_id"],
                      "image": imgs.get(r["id"])})
    return {"items": items}


@api("POST", "/api/admin/vendor-products/{pid:int}/review", auth="owner")
def vendor_product_review(ctx):
    db = get_db()
    pid = ctx.params["pid"]
    pv = db.one("SELECT * FROM product_vendors WHERE product_id=?", (pid,))
    if not pv:
        raise ApiError(404, "This is not a vendor product.")
    decision = ctx.get("decision")
    if decision not in ("approve", "reject"):
        raise ApiError(400, "Choose approve or reject.")
    note = text(ctx.get("note"), "Note", required=False, max_len=300)
    if decision == "approve":
        vend = db.one("SELECT u.status FROM vendors v JOIN users u ON u.id=v.user_id WHERE v.id=?", (pv["vendor_id"],))
        if not vend or vend["status"] != "active":
            raise ApiError(400, "This vendor is suspended. Re-activate the vendor first.")
        db.run("UPDATE products SET status='active', updated_at=? WHERE id=?", (now_iso(), pid))
        db.run("UPDATE product_vendors SET approval='approved', note=NULL, updated_at=? WHERE product_id=?", (now_iso(), pid))
    else:
        db.run("UPDATE products SET status='draft', updated_at=? WHERE id=?", (now_iso(), pid))
        db.run("UPDATE product_vendors SET approval='rejected', note=?, updated_at=? WHERE product_id=?", (note or "Not approved", now_iso(), pid))
    audit(ctx.uid, "vendor_product_" + decision, "product", pid, note, ctx.ip)
    vendor_map(force=True)
    return {"ok": True}


# ================================================================ vendor portal
def _me(ctx):
    v = get_db().one("SELECT * FROM vendors WHERE user_id=?", (ctx.uid,))
    if not v:
        raise ApiError(403, "No vendor profile is linked to this account.")
    return v


def _own(db, ctx, pid):
    v = _me(ctx)
    pv = db.one("SELECT * FROM product_vendors WHERE product_id=? AND vendor_id=?", (pid, v["id"]))
    if not pv:
        raise ApiError(404, "Product not found.")
    return v, pv


class _VCtx:
    """Wraps the request so the shared product validator cannot be used to set owner-only fields."""
    def __init__(self, ctx, status):
        self.c, self.status = ctx, status
        self.body = ctx.body

    def get(self, k, default=None):
        if k == "status":
            return self.status
        if k in ("featured", "cost_price", "apply_discount", "discount_pct"):
            return None if k != "cost_price" else 0
        return self.c.get(k, default)


@api("GET", "/api/vendor/me", auth="vendor")
def vendor_me(ctx):
    v = _me(ctx)
    return {"vendor": {k: v[k] for k in ("id", "business_name", "contact_name", "phone", "commission_pct")}}


@api("GET", "/api/vendor/products", auth="vendor")
def vendor_products(ctx):
    db = get_db()
    v = _me(ctx)
    rows = db.all("SELECT p.*, pv.approval, pv.note, c.name AS category FROM product_vendors pv JOIN products p ON p.id=pv.product_id "
                  "LEFT JOIN categories c ON c.id=p.category_id WHERE pv.vendor_id=? ORDER BY p.updated_at DESC", (v["id"],))
    imgs = first_images([r["id"] for r in rows])
    return {"items": [{"id": r["id"], "name": r["name"], "category": r["category"], "price": r["selling_price"], "mrp": r["mrp"],
                       "stock": r["physical_stock"], "approval": r["approval"], "note": r["note"], "status": r["status"],
                       "image": imgs.get(r["id"])} for r in rows]}


@api("GET", "/api/vendor/products/{pid:int}", auth="vendor")
def vendor_product(ctx):
    db = get_db()
    _own(db, ctx, ctx.params["pid"])
    p = db.one("SELECT * FROM products WHERE id=?", (ctx.params["pid"],))
    out = _product_out(db, p, full=True)
    for k in ("cost_price", "margin_pct", "units_sold", "reserved_qty", "unavailable_qty"):
        out.pop(k, None)
    pv = db.one("SELECT approval, note FROM product_vendors WHERE product_id=?", (p["id"],))
    out["approval"], out["note"] = pv["approval"], pv["note"]
    return out


@api("POST", "/api/vendor/products", auth="vendor")
def vendor_add_product(ctx):
    db = get_db()
    v = _me(ctx)
    d = _product_fields(_VCtx(ctx, "draft"), db)
    stock = int(num(ctx.get("stock", 0), "Stock", 0, 1_000_000, integer=True))
    t = now_iso()
    with transaction(db):
        d.update({"slug": unique_slug("products", d["name"]), "physical_stock": 0, "created_at": t, "updated_at": t, "is_sample": 0})
        pid = db.insert("products", d)
        db.run("INSERT INTO product_vendors(product_id, vendor_id, approval, updated_at) VALUES (?, ?, 'pending', ?)", (pid, v["id"], t))
        if stock:
            inventory.admin_adjust(pid, "received", stock, "Opening stock (vendor)", ctx.uid)
        audit(ctx.uid, "vendor_product_create", "product", pid, d["name"], ctx.ip)
    return {"ok": True, "id": pid}


@api("PUT", "/api/vendor/products/{pid:int}", auth="vendor")
def vendor_edit_product(ctx):
    db = get_db()
    pid = ctx.params["pid"]
    v, pv = _own(db, ctx, pid)
    old = db.one("SELECT * FROM products WHERE id=?", (pid,))
    d = _product_fields(_VCtx(ctx, old["status"]), db, pid)
    if d["name"] != old["name"]:
        d["slug"] = unique_slug("products", d["name"], pid)
    d["updated_at"] = now_iso()
    repend = pv["approval"] == "approved" and any(str(d[k] or "") != str(old[k] or "") for k in CONTENT_FIELDS)
    if repend:
        d["status"] = "draft"
    db.update("products", pid, d)
    if repend or pv["approval"] == "rejected":
        db.run("UPDATE product_vendors SET approval='pending', note=NULL, updated_at=? WHERE product_id=?", (now_iso(), pid))
    audit(ctx.uid, "vendor_product_update", "product", pid, d["name"], ctx.ip)
    return {"ok": True, "approval": "pending" if (repend or pv["approval"] == "rejected") else pv["approval"]}


@api("PATCH", "/api/vendor/products/{pid:int}/stock", auth="vendor")
def vendor_set_stock(ctx):
    db = get_db()
    pid = ctx.params["pid"]
    _own(db, ctx, pid)
    new = int(num(ctx.get("stock"), "Stock", 0, 1_000_000, integer=True))
    p = db.one("SELECT physical_stock, reserved_qty, unavailable_qty FROM products WHERE id=?", (pid,))
    delta = new - p["physical_stock"]
    if delta > 0:
        inventory.admin_adjust(pid, "received", delta, "Stock updated by vendor", ctx.uid)
    elif delta < 0:
        inventory.admin_adjust(pid, "adjustment", delta, "Stock updated by vendor", ctx.uid)
    return {"ok": True, "stock": new}


@api("POST", "/api/vendor/products/{pid:int}/images", auth="vendor", multipart=True)
def vendor_upload_images(ctx):
    db = get_db()
    pid = ctx.params["pid"]
    _, pv = _own(db, ctx, pid)
    out = upload_images(ctx)
    if pv["approval"] == "approved":  # new pictures need the owner's OK again
        db.run("UPDATE products SET status='draft', updated_at=? WHERE id=?", (now_iso(), pid))
        db.run("UPDATE product_vendors SET approval='pending', updated_at=? WHERE product_id=?", (now_iso(), pid))
    return out


@api("DELETE", "/api/vendor/images/{iid:int}", auth="vendor")
def vendor_delete_image(ctx):
    db = get_db()
    img = db.one("SELECT product_id FROM product_images WHERE id=?", (ctx.params["iid"],))
    if not img:
        raise ApiError(404, "Image not found.")
    _own(db, ctx, img["product_id"])
    from .admin import delete_image
    return delete_image(ctx)


# ================================================================ orders, earnings, payouts (vendor business view)
REVERSED = ("returned", "refund_processing", "refunded", "cancelled")
ON_HOLD = ("return_requested", "return_in_progress")
NO_SHIP = ("payment_pending", "cancelled", "cancel_requested", "returned", "refund_processing", "refunded",
           "return_requested", "return_in_progress", "delivered")
RETURN_VIEW = ("cancel_requested", "return_requested", "return_in_progress", "returned", "refund_processing", "refunded")


def sync_earnings(db, vendor_id=None):
    """Create a commission record for every delivered item of a vendor (safe to run any number of times)."""
    where, params = "", []
    if vendor_id:
        where, params = " AND pv.vendor_id=?", [vendor_id]
    rows = db.all("SELECT i.id AS item_id, i.order_id, i.line_total, pv.vendor_id, v.commission_pct FROM order_items i "
                  "JOIN orders o ON o.id=i.order_id JOIN product_vendors pv ON pv.product_id=i.product_id "
                  "JOIN vendors v ON v.id=pv.vendor_id LEFT JOIN vendor_earnings e ON e.order_item_id=i.id "
                  "WHERE e.order_item_id IS NULL AND o.delivered_at IS NOT NULL AND o.status IN ('delivered','return_requested','return_in_progress')" + where, params)
    for r in rows:
        gross = money(r["line_total"])
        comm = money(gross * float(r["commission_pct"]) / 100)
        db.run("INSERT INTO vendor_earnings(order_item_id, order_id, vendor_id, gross, commission_pct, commission, net, created_at) VALUES (?,?,?,?,?,?,?,?)",
               (r["item_id"], r["order_id"], r["vendor_id"], gross, r["commission_pct"], comm, money(gross - comm), now_iso()))


def _earn_state(r, window):
    st = r["order_status"]
    if st in REVERSED:
        return "reversed"
    if st in ON_HOLD:
        return "hold"
    if r["delivered_at"] and parse_iso(r["delivered_at"]) + timedelta(days=window) > now_utc():
        return "clearing"
    return "payable"


def ledger(db, vendor_id):
    """Everything a vendor has earned, with what is payable now, still clearing, on hold or already paid."""
    sync_earnings(db, vendor_id)
    window = int(get_settings().get("return_window_days") or 7)
    rows = db.all("SELECT e.*, o.order_no, o.status AS order_status, o.delivered_at, i.name, i.qty FROM vendor_earnings e "
                  "JOIN orders o ON o.id=e.order_id JOIN order_items i ON i.id=e.order_item_id WHERE e.vendor_id=? ORDER BY e.created_at DESC, e.order_item_id DESC",
                  (vendor_id,))
    sums = {"payable": 0.0, "clearing": 0.0, "hold": 0.0, "paid": 0.0, "clawback": 0.0, "commission": 0.0, "gross": 0.0}
    for r in rows:
        s = _earn_state(r, window)
        r["state"] = s
        if r["payout_id"]:
            r["label"] = "Paid" if s != "reversed" else "Returned after payment"
            if s == "reversed":
                if not r["claw_payout_id"]:
                    sums["clawback"] += r["net"]
            else:
                sums["paid"] += r["net"]
        else:
            r["label"] = {"payable": "Ready to pay", "clearing": "Clearing (return window)", "hold": "On hold (return)", "reversed": "Cancelled / returned"}[s]
            if s in ("payable", "clearing", "hold"):
                sums[s] += r["net"]
        if s != "reversed":
            sums["commission"] += r["commission"]
            sums["gross"] += r["gross"]
    sums = {k: money(v) for k, v in sums.items()}
    sums["due_now"] = money(sums["payable"] - sums["clawback"])
    sums["window_days"] = window
    return sums, rows


# ---------------- owner: ledger + payouts
@api("GET", "/api/admin/vendors/{vid:int}/ledger", auth="owner")
def vendor_ledger_admin(ctx):
    db = get_db()
    v = db.one("SELECT * FROM vendors WHERE id=?", (ctx.params["vid"],))
    if not v:
        raise ApiError(404, "Vendor not found.")
    sums, rows = ledger(db, v["id"])
    pays = db.all("SELECT * FROM vendor_payouts WHERE vendor_id=? ORDER BY id DESC", (v["id"],))
    return {"vendor": {k: v[k] for k in ("id", "business_name", "contact_name", "phone", "bank_holder", "bank_account", "bank_ifsc", "upi", "commission_pct")},
            "summary": sums, "payouts": pays, "rows": rows[:100]}


@api("POST", "/api/admin/vendors/{vid:int}/payouts", auth="owner")
def vendor_payout_create(ctx):
    db = get_db()
    v = db.one("SELECT * FROM vendors WHERE id=?", (ctx.params["vid"],))
    if not v:
        raise ApiError(404, "Vendor not found.")
    method = ctx.get("method")
    if method not in ("upi", "bank", "cash"):
        raise ApiError(400, "Choose how you paid: UPI, bank transfer or cash.")
    ref = text(ctx.get("reference"), "Reference / UTR", required=False, max_len=80)
    note = text(ctx.get("note"), "Note", required=False, max_len=200)
    with transaction(db):
        sums, rows = ledger(db, v["id"])
        expected = num(ctx.get("amount"), "Amount")
        if abs(expected - sums["due_now"]) > 0.01:
            raise ApiError(409, "The amount changed while you were paying. Close this window and open it again.")
        if sums["due_now"] <= 0:
            raise ApiError(400, "Nothing is ready to pay for this vendor yet.")
        pid = db.insert("vendor_payouts", {"vendor_id": v["id"], "amount": sums["due_now"], "method": method, "reference": ref,
                                           "note": note, "created_by": ctx.uid, "created_at": now_iso()})
        for r in rows:
            if r["state"] == "payable" and not r["payout_id"]:
                db.run("UPDATE vendor_earnings SET payout_id=? WHERE order_item_id=?", (pid, r["order_item_id"]))
            elif r["state"] == "reversed" and r["payout_id"] and not r["claw_payout_id"]:
                db.run("UPDATE vendor_earnings SET claw_payout_id=? WHERE order_item_id=?", (pid, r["order_item_id"]))
        audit(ctx.uid, "vendor_payout", "vendor", v["id"], f"{sums['due_now']} via {method}", ctx.ip)
    notify(v["user_id"], "Payment sent to you", f"The store paid you ₹{sums['due_now']:.2f} ({method.upper()}).", None, email=False)
    return {"ok": True, "id": pid, "amount": sums["due_now"]}


# ---------------- vendor: business dashboard
def _my_items_sql(extra=""):
    return ("FROM order_items i JOIN orders o ON o.id=i.order_id JOIN product_vendors pv ON pv.product_id=i.product_id "
            "WHERE pv.vendor_id=? " + extra)


SALE_OK = "o.status NOT IN ('payment_pending','cancelled','returned','refund_processing','refunded')"


@api("GET", "/api/vendor/overview", auth="vendor")
def vendor_overview(ctx):
    db = get_db()
    v = _me(ctx)
    today = local_today()
    t0, w0, m0 = (local_day_start_utc(today), local_day_start_utc(today - timedelta(days=6)), local_day_start_utc(today - timedelta(days=29)))

    def sales(since):
        r = db.one("SELECT COALESCE(SUM(i.line_total),0) AS amt, COUNT(DISTINCT o.id) AS n, COALESCE(SUM(i.qty),0) AS units " + _my_items_sql(f"AND {SALE_OK} AND o.created_at>=?"), (v["id"], since))
        return {"amount": money(r["amt"]), "orders": r["n"], "units": r["units"]}

    rows = db.all("SELECT o.created_at, i.line_total " + _my_items_sql(f"AND {SALE_OK} AND o.created_at>=?"), (v["id"], m0))
    days = {str(today - timedelta(days=k)): 0.0 for k in range(29, -1, -1)}
    for r in rows:
        d = str(local_date(r["created_at"]))
        if d in days:
            days[d] += r["line_total"]
    top = db.all("SELECT i.name, SUM(i.qty) AS units, SUM(i.line_total) AS revenue " + _my_items_sql(f"AND {SALE_OK} AND o.created_at>=? GROUP BY i.product_id, i.name ORDER BY revenue DESC LIMIT 5"), (v["id"], m0))
    ship_ids = db.all("SELECT DISTINCT o.id " + _my_items_sql(f"AND o.status NOT IN {NO_SHIP_SQL} AND (o.payment_method='cod' OR o.status<>'placed') "
                      "AND COALESCE((SELECT f.status FROM vendor_fulfillment f WHERE f.order_id=o.id AND f.vendor_id=pv.vendor_id),'new')<>'shipped'"), (v["id"],))
    low = db.all("SELECT p.id, p.name, (p.physical_stock-p.reserved_qty-p.unavailable_qty) AS avail FROM products p JOIN product_vendors pv ON pv.product_id=p.id "
                 "WHERE pv.vendor_id=? AND pv.approval='approved' AND (p.physical_stock-p.reserved_qty-p.unavailable_qty)<=COALESCE(p.low_stock_threshold,10) ORDER BY avail LIMIT 8", (v["id"],))
    sums, _ = ledger(db, v["id"])
    return {"today": sales(t0), "week": sales(w0), "month": sales(m0), "to_ship": len(ship_ids), "low_stock": low,
            "pending_products": db.val("SELECT COUNT(*) FROM product_vendors WHERE vendor_id=? AND approval='pending'", (v["id"],)),
            "series": [{"day": d, "amount": money(a)} for d, a in days.items()], "top": [{"name": r["name"], "units": r["units"], "revenue": money(r["revenue"])} for r in top],
            "earnings": sums, "commission_pct": v["commission_pct"]}


NO_SHIP_SQL = "('" + "','".join(NO_SHIP) + "')"


def _vendor_order(db, o, vid):
    items = db.all("SELECT i.id, i.name, i.qty, i.unit_price, i.line_total, i.product_id FROM order_items i JOIN product_vendors pv ON pv.product_id=i.product_id "
                   "WHERE i.order_id=? AND pv.vendor_id=?", (o["id"], vid))
    imgs = first_images([i["product_id"] for i in items if i["product_id"]])
    f = db.one("SELECT status, courier, tracking_no FROM vendor_fulfillment WHERE order_id=? AND vendor_id=?", (o["id"], vid)) or {"status": "new", "courier": None, "tracking_no": None}
    addr = jload(o["ship_address"], {}) or {}
    can_act = o["status"] not in NO_SHIP and (o["payment_method"] == "cod" or o["status"] != "placed")
    return {"id": o["id"], "order_no": o["order_no"], "created_at": o["created_at"], "status": o["status"], "status_label": osvc.STATUS_LABEL.get(o["status"], o["status"]),
            "cod": o["payment_method"] == "cod", "ship_name": o["ship_name"], "ship_phone": o["ship_phone"],
            "address": ", ".join(str(addr[k]) for k in ("line1", "line2", "city", "state", "pincode") if addr.get(k)) or (o["ship_address"] if isinstance(o["ship_address"], str) and not addr else ""),
            "items": [{**i, "image": imgs.get(i["product_id"])} for i in items], "total": money(sum(i["line_total"] for i in items)),
            "fulfil": f["status"], "courier": f["courier"], "tracking_no": f["tracking_no"], "can_act": bool(can_act)}


@api("GET", "/api/vendor/orders", auth="vendor")
def vendor_orders(ctx):
    db = get_db()
    v = _me(ctx)
    flt = ctx.q("filter", "to_ship")
    extra, params = "", [v["id"]]
    ful = "COALESCE((SELECT f.status FROM vendor_fulfillment f WHERE f.order_id=o.id AND f.vendor_id=pv.vendor_id),'new')"
    if flt == "to_ship":
        extra = f"AND o.status NOT IN {NO_SHIP_SQL} AND (o.payment_method='cod' OR o.status<>'placed') AND {ful}<>'shipped'"
    elif flt == "shipped":
        extra = f"AND {ful}='shipped' AND o.status NOT IN ('delivered','cancelled','returned','refunded')"
    elif flt == "delivered":
        extra = "AND o.status='delivered'"
    elif flt == "returns":
        extra = "AND o.status IN ('" + "','".join(RETURN_VIEW) + "')"
    elif flt == "waiting":
        extra = "AND o.status='payment_pending'"
    ids = db.all("SELECT DISTINCT o.id, o.created_at " + _my_items_sql(extra + " ORDER BY o.created_at DESC LIMIT 100"), tuple(params))
    out = []
    for r in ids:
        o = db.one("SELECT * FROM orders WHERE id=?", (r["id"],))
        out.append(_vendor_order(db, o, v["id"]))
    return {"items": out}


@api("POST", "/api/vendor/orders/{oid:int}/fulfil", auth="vendor")
def vendor_fulfil(ctx):
    db = get_db()
    v = _me(ctx)
    oid = ctx.params["oid"]
    if not db.one("SELECT 1 FROM order_items i JOIN product_vendors pv ON pv.product_id=i.product_id WHERE i.order_id=? AND pv.vendor_id=?", (oid, v["id"])):
        raise ApiError(404, "Order not found.")
    o = db.one("SELECT * FROM orders WHERE id=?", (oid,))
    if o["status"] in NO_SHIP or (o["payment_method"] != "cod" and o["status"] == "placed"):
        raise ApiError(400, "This order cannot be packed or shipped right now.")
    action = ctx.get("action")
    if action not in ("pack", "ship"):
        raise ApiError(400, "Choose pack or ship.")
    cur = db.one("SELECT * FROM vendor_fulfillment WHERE order_id=? AND vendor_id=?", (oid, v["id"]))
    courier = text(ctx.get("courier"), "Courier", required=False, max_len=60)
    track = text(ctx.get("tracking_no"), "Tracking number", required=(action == "ship"), max_len=60)
    new = "packed" if action == "pack" else "shipped"
    if cur and cur["status"] == "shipped":
        raise ApiError(400, "You already marked this order as shipped.")
    t = now_iso()
    if cur:
        db.run("UPDATE vendor_fulfillment SET status=?, courier=COALESCE(?,courier), tracking_no=COALESCE(?,tracking_no), updated_at=? WHERE order_id=? AND vendor_id=?", (new, courier, track, t, oid, v["id"]))
    else:
        db.run("INSERT INTO vendor_fulfillment(order_id, vendor_id, status, courier, tracking_no, updated_at) VALUES (?,?,?,?,?,?)", (oid, v["id"], new, courier, track, t))
    osvc.add_event(db, oid, o["status"], f"{v['business_name']}: {'packed their items' if action == 'pack' else 'shipped their items — ' + (courier or 'Courier') + ' ' + (track or '')}", ctx.uid, visible=False)
    for ow in db.all("SELECT id FROM users WHERE role='owner' AND status='active'"):
        notify(ow["id"], f"{v['business_name']}: order {o['order_no']} {'packed' if action == 'pack' else 'shipped'}",
               "Open the order and update its status." , f"#/orders", email=False)
    audit(ctx.uid, "vendor_" + action, "order", oid, v["business_name"], ctx.ip)
    return {"ok": True, "fulfil": new}


@api("GET", "/api/vendor/earnings", auth="vendor")
def vendor_earnings(ctx):
    db = get_db()
    v = _me(ctx)
    sums, rows = ledger(db, v["id"])
    pays = db.all("SELECT id, amount, method, reference, note, created_at FROM vendor_payouts WHERE vendor_id=? ORDER BY id DESC", (v["id"],))
    return {"summary": sums, "payouts": pays,
            "rows": [{k: r[k] for k in ("order_no", "name", "qty", "gross", "commission_pct", "commission", "net", "label", "state", "created_at")} for r in rows[:200]]}


def _range(ctx):
    today = local_today()
    start = ctx.q("from") or str(today - timedelta(days=29))
    end = ctx.q("to") or str(today)
    try:
        s = local_day_start_utc(date.fromisoformat(start))
        e = local_day_start_utc(date.fromisoformat(end) + timedelta(days=1))
    except ValueError:
        raise ApiError(400, "Dates must look like 2026-10-31.")
    return start, end, s, e


@api("GET", "/api/vendor/report", auth="vendor")
def vendor_report(ctx):
    db = get_db()
    v = _me(ctx)
    kind = ctx.q("kind", "sales")
    start, end, s, e = _range(ctx)
    buf = io.StringIO()
    w = csv.writer(buf)
    if kind == "earnings":
        sums, rows = ledger(db, v["id"])
        w.writerow(["Order", "Product", "Qty", "Sale amount", "Commission %", "Commission", "You earn", "Status", "Date"])
        for r in rows:
            if s <= r["created_at"] < e:
                w.writerow([r["order_no"], r["name"], r["qty"], r["gross"], r["commission_pct"], r["commission"], r["net"], r["label"], r["created_at"][:10]])
    elif kind == "payouts":
        w.writerow(["Date", "Amount", "Method", "Reference", "Note"])
        for p in db.all("SELECT * FROM vendor_payouts WHERE vendor_id=? AND created_at>=? AND created_at<? ORDER BY id", (v["id"], s, e)):
            w.writerow([p["created_at"][:10], p["amount"], p["method"], p["reference"] or "", p["note"] or ""])
    else:
        w.writerow(["Date", "Order", "Product", "Qty", "Price", "Amount", "Order status"])
        for r in db.all("SELECT o.created_at, o.order_no, o.status, i.name, i.qty, i.unit_price, i.line_total " + _my_items_sql("AND o.created_at>=? AND o.created_at<? ORDER BY o.created_at"), (v["id"], s, e)):
            w.writerow([str(local_date(r["created_at"])), r["order_no"], r["name"], r["qty"], r["unit_price"], r["line_total"], osvc.STATUS_LABEL.get(r["status"], r["status"])])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{kind}-{start}-to-{end}.csv"'})


# ================================================================ public shop page + vendor shop settings
@api("GET", "/api/shops/{vid:int}")
def shop_public(ctx):
    db = get_db()
    v = db.one("SELECT v.id, v.business_name, u.status FROM vendors v JOIN users u ON u.id=v.user_id WHERE v.id=?", (ctx.params["vid"],))
    if not v or v["status"] != "active":
        raise ApiError(404, "This shop is not available.")
    prof = db.one("SELECT about, logo_url FROM vendor_profiles WHERE vendor_id=?", (v["id"],)) or {}
    rows = db.all("SELECT p.* FROM product_vendors pv JOIN products p ON p.id=pv.product_id WHERE pv.vendor_id=? AND pv.approval='approved' "
                  "AND p.status IN ('active','out_of_stock') ORDER BY p.units_sold DESC, p.id DESC LIMIT 200", (v["id"],))
    imgs = first_images([r["id"] for r in rows])
    return {"id": v["id"], "name": v["business_name"], "about": prof.get("about"), "logo": prof.get("logo_url"),
            "items": [product_card(r, imgs.get(r["id"])) for r in rows]}


@api("GET", "/api/vendor/shop", auth="vendor")
def vendor_shop_get(ctx):
    v = _me(ctx)
    prof = get_db().one("SELECT about, logo_url FROM vendor_profiles WHERE vendor_id=?", (v["id"],)) or {}
    return {"id": v["id"], "name": v["business_name"], "about": prof.get("about") or "", "logo": prof.get("logo_url")}


def _save_profile(db, vid, **fields):
    if db.one("SELECT 1 FROM vendor_profiles WHERE vendor_id=?", (vid,)):
        for k, val in fields.items():
            db.run(f"UPDATE vendor_profiles SET {k}=?, updated_at=? WHERE vendor_id=?", (val, now_iso(), vid))
    else:
        db.run("INSERT INTO vendor_profiles(vendor_id, about, logo_url, updated_at) VALUES (?,?,?,?)", (vid, fields.get("about"), fields.get("logo_url"), now_iso()))


@api("PUT", "/api/vendor/shop", auth="vendor")
def vendor_shop_save(ctx):
    db = get_db()
    v = _me(ctx)
    _save_profile(db, v["id"], about=text(ctx.get("about"), "About your shop", required=False, max_len=600) or "")
    return {"ok": True}


@api("POST", "/api/vendor/shop/logo", auth="vendor", multipart=True)
def vendor_shop_logo(ctx):
    db = get_db()
    v = _me(ctx)
    f = ctx.form.get("file") if ctx.form else None
    if f is None or not hasattr(f, "file"):
        raise ApiError(400, "Choose a picture first.")
    f.file.seek(0)
    data = f.file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise ApiError(400, "Picture is larger than 5 MB.")
    ext = _sniff(data)
    if not ext:
        raise ApiError(400, "Only JPG, PNG, WEBP or GIF pictures are allowed.")
    import secrets
    name = f"{v['id']}_{secrets.token_hex(8)}.{ext}"
    save_file(f"vendors/{name}", {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}[ext], data)
    old = db.one("SELECT logo_url FROM vendor_profiles WHERE vendor_id=?", (v["id"],))
    _save_profile(db, v["id"], logo_url=f"/uploads/vendors/{name}")
    if old and old["logo_url"]:
        delete_file(old["logo_url"].replace("/uploads/", "", 1))
    return {"ok": True, "logo": f"/uploads/vendors/{name}"}
