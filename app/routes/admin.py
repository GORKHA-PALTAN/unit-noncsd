"""Owner / staff API. Every route is protected server-side by role + permission checks."""
import csv
import io
import re
import secrets
from ..services import mailer as _mailer
from datetime import date

from starlette.responses import Response

from .. import config
from ..db import IS_PG, get_db, jdump, jload, now_iso, transaction
from ..security import PERMISSIONS, audit, destroy_user_sessions, hash_password, password_problem
from ..services import analytics, inventory, reports
from ..services import orders as osvc
from ..services import payments as psvc
from ..services.common import (DEFAULT_SETTINGS, save_file, delete_file, available, discount_pct, first_images, get_settings, money, notify,
                               set_settings, slugify, unique_slug)
from ..web import ApiError, api, num, page_args, text
from .auth import EMAIL_RE

PRODUCT_STATUSES = ("active", "inactive", "draft", "out_of_stock")


def _like(s):
    return f"%{s.lower()}%"


# ================================================================ overview
@api("GET", "/api/admin/overview", auth="admin")
def overview(ctx):
    osvc.expire_stale_payments()
    data = reports.overview(ctx.q("range", "30d"), ctx.q("from"), ctx.q("to"))
    from ..security import has_perm
    if not has_perm(ctx.user, "finance"):
        for k in ("cogs", "gross_profit", "gross_margin_pct", "expenses", "net_profit", "net_revenue_ex_tax", "expense_entries"):
            data["sales"].pop(k, None)
        data["products"].pop("valuation_cost", None)
    return data


# ================================================================ categories
@api("GET", "/api/admin/categories", auth="admin")
def categories(ctx):
    db = get_db()
    rows = db.all("SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.category_id=c.id OR p.subcategory_id=c.id) AS products "
                  "FROM categories c ORDER BY COALESCE(c.parent_id, c.id), c.parent_id IS NOT NULL, c.sort, c.name")
    return {"items": rows}


def _cat_fields(ctx, db, cid=None):
    name = text(ctx.get("name"), "Name", max_len=60)
    parent = ctx.get("parent_id") or None
    if parent:
        parent = int(parent)
        prow = db.one("SELECT * FROM categories WHERE id=?", (parent,))
        if not prow or prow["parent_id"]:
            raise ApiError(400, "Subcategories can only be created under a top-level category.")
        if cid and parent == cid:
            raise ApiError(400, "A category cannot be its own parent.")
    return {"name": name, "parent_id": parent, "department": text(ctx.get("department"), "Department", required=False, max_len=40),
            "icon": text(ctx.get("icon"), "Icon", required=False, max_len=30),
            "color": text(ctx.get("color"), "Colour", required=False, max_len=20),
            "sort": int(num(ctx.get("sort", 0), "Sort", integer=True, required=False) or 0),
            "active": 1 if ctx.get("active", True) else 0,
            "default_tax_rate": num(ctx.get("default_tax_rate", 18), "Tax rate", 0, 40)}


@api("POST", "/api/admin/categories", auth="admin", perm="products")
def add_category(ctx):
    db = get_db()
    d = _cat_fields(ctx, db)
    d["slug"] = unique_slug("categories", d["name"])
    d["created_at"] = now_iso()
    cid = db.insert("categories", d)
    audit(ctx.uid, "category_create", "category", cid, d["name"], ctx.ip)
    return db.one("SELECT * FROM categories WHERE id=?", (cid,))


@api("PUT", "/api/admin/categories/{cid:int}", auth="admin", perm="products")
def edit_category(ctx):
    db = get_db()
    cid = ctx.params["cid"]
    if not db.one("SELECT id FROM categories WHERE id=?", (cid,)):
        raise ApiError(404, "Category not found.")
    d = _cat_fields(ctx, db, cid)
    if d["parent_id"] and db.one("SELECT id FROM categories WHERE parent_id=?", (cid,)):
        raise ApiError(400, "This category has subcategories, so it must stay top-level.")
    db.update("categories", cid, d)
    audit(ctx.uid, "category_update", "category", cid, d["name"], ctx.ip)
    return db.one("SELECT * FROM categories WHERE id=?", (cid,))


@api("DELETE", "/api/admin/categories/{cid:int}", auth="admin", perm="products")
def delete_category(ctx):
    db = get_db()
    cid = ctx.params["cid"]
    if db.val("SELECT COUNT(*) FROM products WHERE category_id=? OR subcategory_id=?", (cid, cid)):
        raise ApiError(400, "Move or delete the products in this category first.")
    if db.one("SELECT id FROM categories WHERE parent_id=?", (cid,)):
        raise ApiError(400, "Delete its subcategories first.")
    db.run("DELETE FROM categories WHERE id=?", (cid,))
    audit(ctx.uid, "category_delete", "category", cid, None, ctx.ip)
    return {"ok": True}


# ================================================================ products
def _product_out(db, p, full=False):
    out = dict(p)
    out["available"] = available(p)
    out["discount_pct"] = discount_pct(p)
    out["specs"] = jload(p["specs"], {})
    out["margin_pct"] = round((p["selling_price"] - p["cost_price"]) / p["selling_price"] * 100, 1) if p["selling_price"] else None
    if full:
        out["images"] = db.all("SELECT id, url, sort FROM product_images WHERE product_id=? ORDER BY sort, id", (p["id"],))
    return out


@api("GET", "/api/admin/products", auth="admin")
def admin_products(ctx):
    db = get_db()
    where, params = ["1=1"], []
    if ctx.q("q"):
        where.append("(LOWER(p.name) LIKE ? OR LOWER(p.sku) LIKE ? OR LOWER(p.brand) LIKE ?)")
        params += [_like(ctx.q("q"))] * 3
    if ctx.q("status"):
        where.append("p.status=?"); params.append(ctx.q("status"))
    if ctx.q("category"):
        where.append("(p.category_id=? OR p.subcategory_id=?)"); params += [int(ctx.q("category"))] * 2
    if ctx.q("stock") == "low":
        where.append("(p.physical_stock - p.reserved_qty - p.unavailable_qty) BETWEEN 1 AND p.low_stock_threshold")
    elif ctx.q("stock") == "out":
        where.append("(p.physical_stock - p.reserved_qty - p.unavailable_qty) <= 0")
    if ctx.q("sample") in ("0", "1"):
        where.append("p.is_sample=?"); params.append(int(ctx.q("sample")))
    w = " AND ".join(where)
    sort = {"name": "p.name", "price": "p.selling_price DESC", "stock": "(p.physical_stock - p.reserved_qty - p.unavailable_qty)",
            "sold": "p.units_sold DESC", "updated": "p.updated_at DESC"}.get(ctx.q("sort"), "p.updated_at DESC")
    total = db.val(f"SELECT COUNT(*) FROM products p WHERE {w}", params)
    page, per, off = page_args(ctx, 25, 200)
    rows = db.all(f"SELECT p.*, c.name AS category, sc.name AS subcategory FROM products p LEFT JOIN categories c ON c.id=p.category_id "
                  f"LEFT JOIN categories sc ON sc.id=p.subcategory_id WHERE {w} ORDER BY {sort}, p.id DESC LIMIT {per} OFFSET {off}", params)
    imgs = first_images([r["id"] for r in rows])
    from ..security import has_perm
    show_cost = has_perm(ctx.user, "finance") or has_perm(ctx.user, "products")
    items = []
    for r in rows:
        o = _product_out(db, r)
        o["image"] = imgs.get(r["id"])
        if not show_cost:
            o.pop("cost_price", None); o.pop("margin_pct", None)
        items.append(o)
    return {"items": items, "total": total, "page": page, "per": per}


@api("GET", "/api/admin/products/{pid:int}", auth="admin")
def admin_product(ctx):
    db = get_db()
    p = db.one("SELECT * FROM products WHERE id=?", (ctx.params["pid"],))
    if not p:
        raise ApiError(404, "Product not found.")
    out = _product_out(db, p, full=True)
    out["movements"] = db.all("SELECT m.*, u.name AS by_user, o.order_no FROM inventory_movements m LEFT JOIN users u ON u.id=m.actor_id "
                              "LEFT JOIN orders o ON o.id=m.order_id WHERE m.product_id=? ORDER BY m.id DESC LIMIT 30", (p["id"],))
    return out


def _product_fields(ctx, db, pid=None):
    d = {}
    d["name"] = text(ctx.get("name"), "Product name", max_len=150, min_len=2)
    d["description"] = text(ctx.get("description"), "Description", required=False, max_len=5000)
    d["brand"] = text(ctx.get("brand"), "Brand", required=False, max_len=60)
    cat = ctx.get("category_id")
    if not cat:
        raise ApiError(400, "Category is required.")
    crow = db.one("SELECT * FROM categories WHERE id=?", (int(cat),))
    if not crow or crow["parent_id"]:
        raise ApiError(400, "Choose a valid top-level category.")
    d["category_id"] = crow["id"]
    sub = ctx.get("subcategory_id") or None
    if sub:
        srow = db.one("SELECT * FROM categories WHERE id=?", (int(sub),))
        if not srow or srow["parent_id"] != crow["id"]:
            raise ApiError(400, "Subcategory does not belong to the chosen category.")
        d["subcategory_id"] = srow["id"]
    else:
        d["subcategory_id"] = None
    sku = text(ctx.get("sku"), "SKU", required=False, max_len=40)
    if not sku:
        sku = f"{slugify(crow['name'])[:3].upper()}-{secrets.token_hex(3).upper()}"
    if not re.fullmatch(r"[A-Za-z0-9\-_.]+", sku):
        raise ApiError(400, "SKU may contain only letters, numbers, dashes, dots and underscores.")
    clash = db.one("SELECT id FROM products WHERE sku=?", (sku,))
    if clash and clash["id"] != pid:
        raise ApiError(409, "Another product already uses this SKU.")
    d["sku"] = sku
    d["selling_price"] = money(num(ctx.get("selling_price"), "Selling price", lo=0.01, hi=10_000_000))
    d["cost_price"] = money(num(ctx.get("cost_price", 0), "Cost price", lo=0, hi=10_000_000, required=False) or 0)
    mrp = num(ctx.get("mrp"), "MRP", lo=0, hi=10_000_000, required=False)
    if mrp is not None and mrp and mrp < d["selling_price"]:
        raise ApiError(400, "MRP cannot be lower than the selling price.")
    d["mrp"] = money(mrp) if mrp else None
    # Optional: compute selling price from MRP and discount %
    disc = num(ctx.get("discount_pct"), "Discount %", lo=0, hi=95, required=False)
    if disc is not None and d["mrp"] and ctx.get("apply_discount"):
        d["selling_price"] = money(d["mrp"] * (1 - disc / 100))
    d["tax_rate"] = num(ctx.get("tax_rate", crow["default_tax_rate"]), "GST rate", 0, 40)
    d["low_stock_threshold"] = int(num(ctx.get("low_stock_threshold", 10), "Low-stock threshold", 0, 100000, integer=True))
    d["max_per_order"] = int(num(ctx.get("max_per_order", 10), "Max per order", 1, 999, integer=True))
    d["weight_g"] = num(ctx.get("weight_g"), "Weight", 0, 1_000_000, integer=True, required=False)
    d["dimensions"] = text(ctx.get("dimensions"), "Dimensions", required=False, max_len=60)
    d["shipping_req"] = text(ctx.get("shipping_req"), "Shipping requirements", required=False, max_len=200)
    status = ctx.get("status", "draft")
    if status not in PRODUCT_STATUSES:
        raise ApiError(400, "Invalid product status.")
    d["status"] = status
    d["featured"] = 1 if ctx.get("featured") else 0
    specs = ctx.get("specs") or {}
    if not isinstance(specs, dict) or len(specs) > 40:
        raise ApiError(400, "Specifications must be a list of up to 40 name/value pairs.")
    d["specs"] = jdump({str(k)[:60]: str(v)[:300] for k, v in specs.items() if str(k).strip()})
    return d


@api("POST", "/api/admin/products", auth="admin", perm="products")
def add_product(ctx):
    db = get_db()
    d = _product_fields(ctx, db)
    stock = int(num(ctx.get("stock", 0), "Opening stock", 0, 10_000_000, integer=True))
    t = now_iso()
    with transaction(db):
        d.update({"slug": unique_slug("products", d["name"]), "physical_stock": 0, "created_at": t, "updated_at": t, "is_sample": 0})
        pid = db.insert("products", d)
        if stock:
            inventory.admin_adjust(pid, "received", stock, "Opening stock", ctx.uid)
        audit(ctx.uid, "product_create", "product", pid, d["name"], ctx.ip)
    return _product_out(db, db.one("SELECT * FROM products WHERE id=?", (pid,)), full=True)


@api("PUT", "/api/admin/products/{pid:int}", auth="admin", perm="products")
def edit_product(ctx):
    db = get_db()
    pid = ctx.params["pid"]
    old = db.one("SELECT * FROM products WHERE id=?", (pid,))
    if not old:
        raise ApiError(404, "Product not found.")
    d = _product_fields(ctx, db, pid)
    if d["name"] != old["name"]:
        d["slug"] = unique_slug("products", d["name"], pid)
    d["updated_at"] = now_iso()
    db.update("products", pid, d)
    changes = [f"{k}: {old[k]} → {d[k]}" for k in ("selling_price", "mrp", "cost_price", "status") if str(old[k]) != str(d[k])]
    audit(ctx.uid, "product_update", "product", pid, "; ".join(changes) or d["name"], ctx.ip)
    return _product_out(db, db.one("SELECT * FROM products WHERE id=?", (pid,)), full=True)


@api("PATCH", "/api/admin/products/{pid:int}", auth="admin", perm="products")
def quick_edit_product(ctx):
    """Quick inline edits: price, MRP, status, featured."""
    db = get_db()
    pid = ctx.params["pid"]
    p = db.one("SELECT * FROM products WHERE id=?", (pid,))
    if not p:
        raise ApiError(404, "Product not found.")
    d = {}
    if "selling_price" in ctx.body:
        d["selling_price"] = money(num(ctx.get("selling_price"), "Selling price", lo=0.01))
    if "mrp" in ctx.body:
        d["mrp"] = money(num(ctx.get("mrp"), "MRP", lo=0, required=False) or 0) or None
    sp, mrp = d.get("selling_price", p["selling_price"]), d.get("mrp", p["mrp"])
    if mrp and mrp < sp:
        raise ApiError(400, "MRP cannot be lower than the selling price.")
    if "status" in ctx.body:
        if ctx.get("status") not in PRODUCT_STATUSES:
            raise ApiError(400, "Invalid status.")
        d["status"] = ctx.get("status")
    if "featured" in ctx.body:
        d["featured"] = 1 if ctx.get("featured") else 0
    if not d:
        raise ApiError(400, "Nothing to update.")
    d["updated_at"] = now_iso()
    db.update("products", pid, d)
    audit(ctx.uid, "product_quick_edit", "product", pid, jdump({k: v for k, v in d.items() if k != "updated_at"}), ctx.ip)
    return _product_out(db, db.one("SELECT * FROM products WHERE id=?", (pid,)))


@api("DELETE", "/api/admin/products/{pid:int}", auth="admin", perm="products")
def delete_product(ctx):
    db = get_db()
    pid = ctx.params["pid"]
    p = db.one("SELECT * FROM products WHERE id=?", (pid,))
    if not p:
        raise ApiError(404, "Product not found.")
    if p["reserved_qty"] > 0:
        raise ApiError(400, "This product has stock reserved for open orders. Set it to Inactive instead.")
    has_orders = db.one("SELECT id FROM order_items WHERE product_id=? LIMIT 1", (pid,))
    with transaction(db):
        if has_orders:
            # keep sales history intact: archive instead of hard delete
            db.update("products", pid, {"status": "inactive", "updated_at": now_iso(), "featured": 0})
            db.run("DELETE FROM cart_items WHERE product_id=?", (pid,))
            msg = "Product has order history, so it was archived (set to Inactive) instead of deleted."
        else:
            db.run("DELETE FROM products WHERE id=?", (pid,))
            msg = "Product deleted."
        audit(ctx.uid, "product_delete", "product", pid, p["name"], ctx.ip)
    return {"ok": True, "message": msg}


IMAGE_SIGS = [(b"\xff\xd8\xff", "jpg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"GIF87a", "gif"), (b"GIF89a", "gif")]


def _sniff(data):
    for sig, ext in IMAGE_SIGS:
        if data.startswith(sig):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@api("POST", "/api/admin/products/{pid:int}/images", auth="admin", perm="products", multipart=True)
def upload_images(ctx):
    db = get_db()
    pid = ctx.params["pid"]
    if not db.one("SELECT id FROM products WHERE id=?", (pid,)):
        raise ApiError(404, "Product not found.")
    files = ctx.form.getlist("files") if ctx.form else []
    if not files:
        raise ApiError(400, "Choose at least one image.")
    if db.val("SELECT COUNT(*) FROM product_images WHERE product_id=?", (pid,)) + len(files) > 8:
        raise ApiError(400, "A product can have at most 8 images.")
    import anyio  # starlette UploadFile methods are async; read synchronously from the spooled file
    saved = []
    for f in files:
        f.file.seek(0)
        data = f.file.read(config.MAX_UPLOAD_BYTES + 1)
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise ApiError(400, f"{f.filename}: image is larger than 5 MB.")
        ext = _sniff(data)
        if not ext:
            raise ApiError(400, f"{f.filename}: only JPG, PNG, WEBP or GIF images are allowed.")
        name = f"{pid}_{secrets.token_hex(8)}.{ext}"
        save_file(f"products/{name}", {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}[ext], data)
        saved.append(f"/uploads/products/{name}")
    start = db.val("SELECT COALESCE(MAX(sort), -1) FROM product_images WHERE product_id=?", (pid,)) + 1
    for i, url in enumerate(saved):
        db.insert("product_images", {"product_id": pid, "url": url, "sort": start + i})
    db.run("UPDATE products SET updated_at=? WHERE id=?", (now_iso(), pid))
    return {"images": db.all("SELECT id, url, sort FROM product_images WHERE product_id=? ORDER BY sort, id", (pid,))}


@api("DELETE", "/api/admin/images/{iid:int}", auth="admin", perm="products")
def delete_image(ctx):
    db = get_db()
    img = db.one("SELECT * FROM product_images WHERE id=?", (ctx.params["iid"],))
    if not img:
        raise ApiError(404, "Image not found.")
    db.run("DELETE FROM product_images WHERE id=?", (img["id"],))
    if img["url"].startswith("/uploads/products/"):
        delete_file("products/" + img["url"].rsplit("/", 1)[-1])
    return {"ok": True}


@api("POST", "/api/admin/images/{iid:int}/primary", auth="admin", perm="products")
def primary_image(ctx):
    db = get_db()
    img = db.one("SELECT * FROM product_images WHERE id=?", (ctx.params["iid"],))
    if not img:
        raise ApiError(404, "Image not found.")
    db.run("UPDATE product_images SET sort=sort+1 WHERE product_id=?", (img["product_id"],))
    db.run("UPDATE product_images SET sort=0 WHERE id=?", (img["id"],))
    return {"ok": True}


# ================================================================ inventory
@api("GET", "/api/admin/inventory", auth="admin", perm="inventory")
def inventory_list(ctx):
    db = get_db()
    where, params = ["p.status <> 'draft' OR p.physical_stock > 0"], []
    if ctx.q("q"):
        where.append("(LOWER(p.name) LIKE ? OR LOWER(p.sku) LIKE ?)"); params += [_like(ctx.q("q"))] * 2
    f = ctx.q("filter")
    if f == "low":
        where.append("(p.physical_stock - p.reserved_qty - p.unavailable_qty) BETWEEN 1 AND p.low_stock_threshold")
    elif f == "out":
        where.append("(p.physical_stock - p.reserved_qty - p.unavailable_qty) <= 0")
    elif f == "reserved":
        where.append("p.reserved_qty > 0")
    elif f == "damaged":
        where.append("p.unavailable_qty > 0")
    w = " AND ".join(f"({x})" for x in where)
    rows = db.all(f"SELECT p.id, p.name, p.sku, p.status, p.physical_stock, p.reserved_qty, p.unavailable_qty, p.units_sold, "
                  f"p.low_stock_threshold, p.cost_price, p.selling_price, c.name AS category FROM products p "
                  f"LEFT JOIN categories c ON c.id=p.category_id WHERE {w} ORDER BY (p.physical_stock - p.reserved_qty - p.unavailable_qty), p.name", params)
    for r in rows:
        r["available"] = available(r)
        r["value_cost"] = money(r["physical_stock"] * r["cost_price"])
        r["level"] = "out" if r["available"] <= 0 else "low" if r["available"] <= r["low_stock_threshold"] else "ok"
    return {"items": rows, "types": inventory.MOVEMENT_TYPES}


@api("POST", "/api/admin/inventory/{pid:int}/adjust", auth="admin", perm="inventory")
def inventory_adjust(ctx):
    mtype = ctx.get("type")
    qty = int(num(ctx.get("qty"), "Quantity", -10_000_000, 10_000_000, integer=True))
    note = text(ctx.get("note"), "Note", required=False, max_len=200)
    if mtype != "adjustment" and qty < 0:
        raise ApiError(400, "Quantity must be positive.")
    db = get_db()
    with transaction(db):
        after = inventory.admin_adjust(ctx.params["pid"], mtype, qty, note, ctx.uid)
        audit(ctx.uid, "stock_" + mtype, "product", ctx.params["pid"], f"{qty} {note or ''}", ctx.ip)
    after["available"] = available(after)
    return after


@api("PUT", "/api/admin/inventory/{pid:int}/threshold", auth="admin", perm="inventory")
def inventory_threshold(ctx):
    v = int(num(ctx.get("low_stock_threshold"), "Threshold", 0, 100000, integer=True))
    get_db().run("UPDATE products SET low_stock_threshold=? WHERE id=?", (v, ctx.params["pid"]))
    return {"ok": True}


@api("GET", "/api/admin/inventory/movements", auth="admin", perm="inventory")
def movements(ctx):
    db = get_db()
    where, params = ["1=1"], []
    if ctx.q("product_id"):
        where.append("m.product_id=?"); params.append(int(ctx.q("product_id")))
    if ctx.q("type"):
        where.append("m.type=?"); params.append(ctx.q("type"))
    page, per, off = page_args(ctx, 50, 200)
    w = " AND ".join(where)
    total = db.val(f"SELECT COUNT(*) FROM inventory_movements m WHERE {w}", params)
    rows = db.all(f"SELECT m.*, p.name, p.sku, u.name AS by_user, o.order_no FROM inventory_movements m JOIN products p ON p.id=m.product_id "
                  f"LEFT JOIN users u ON u.id=m.actor_id LEFT JOIN orders o ON o.id=m.order_id WHERE {w} ORDER BY m.id DESC LIMIT {per} OFFSET {off}",
                  params)
    return {"items": rows, "total": total, "page": page, "per": per, "types": inventory.MOVEMENT_TYPES}


# ================================================================ orders
@api("GET", "/api/admin/orders", auth="admin", perm="orders")
def admin_orders(ctx):
    db = get_db()
    osvc.expire_stale_payments()
    where, params = ["1=1"], []
    st = ctx.q("status")
    groups = {"open": tuple(osvc.OPEN_STATUSES), "to_process": ("placed", "payment_confirmed", "confirmed", "processing", "packed"),
              "shipping": ("dispatched", "in_transit", "out_for_delivery"),
              "returns": ("cancel_requested", "return_requested", "return_in_progress", "refund_processing")}
    if st in groups:
        where.append(f"o.status IN ({','.join('?' for _ in groups[st])})"); params += list(groups[st])
    elif st:
        where.append("o.status=?"); params.append(st)
    if ctx.q("payment"):
        where.append("o.payment_status=?"); params.append(ctx.q("payment"))
    if ctx.q("method"):
        where.append("o.payment_method=?"); params.append(ctx.q("method"))
    if ctx.q("q"):
        where.append("(LOWER(o.order_no) LIKE ? OR LOWER(u.name) LIKE ? OR LOWER(u.email) LIKE ? OR LOWER(o.buyer_code) LIKE ? OR o.ship_phone LIKE ?)")
        params += [_like(ctx.q("q"))] * 5
    if ctx.q("range"):
        a, b = reports.resolve_range(ctx.q("range"), ctx.q("from"), ctx.q("to"))
        s, e = reports._bounds(a, b)
        where.append("o.created_at >= ? AND o.created_at < ?"); params += [s, e]
    if ctx.q("company"):
        where.append("o.buyer_company=?"); params.append(ctx.q("company"))
    w = " AND ".join(where)
    total = db.val(f"SELECT COUNT(*) FROM orders o JOIN users u ON u.id=o.user_id WHERE {w}", params)
    page, per, off = page_args(ctx, 25, 200)
    rows = db.all(f"SELECT o.id, o.order_no, o.status, o.payment_method, o.payment_status, o.grand_total, o.created_at, o.buyer_code, "
                  f"o.is_sample, u.name AS customer, (SELECT SUM(qty) FROM order_items i WHERE i.order_id=o.id) AS units "
                  f"FROM orders o JOIN users u ON u.id=o.user_id WHERE {w} ORDER BY o.created_at DESC LIMIT {per} OFFSET {off}", params)
    for r in rows:
        r["status_label"] = osvc.STATUS_LABEL[r["status"]]
    counts = {r["status"]: r["n"] for r in db.all("SELECT status, COUNT(*) AS n FROM orders GROUP BY status")}
    return {"items": rows, "total": total, "page": page, "per": per, "status_counts": counts,
            "statuses": [{"code": c, "label": l} for c, l in osvc.STATUSES]}


@api("GET", "/api/admin/orders/{oid:int}", auth="admin", perm="orders")
def admin_order(ctx):
    db = get_db()
    o = db.one("SELECT * FROM orders WHERE id=?", (ctx.params["oid"],))
    if not o:
        raise ApiError(404, "Order not found.")
    out = osvc.serialize_order(db, o, admin=True)
    cust = db.one("SELECT u.id, u.name, u.email, u.phone, u.created_at, b.code AS buyer_code FROM users u "
                  "LEFT JOIN buyers b ON b.id=u.buyer_id WHERE u.id=?", (o["user_id"],))
    out["customer"] = cust
    out["payments"] = db.all("SELECT id, method, provider_order_id, provider_payment_id, amount, status, error, created_at, verified_at "
                             "FROM payments WHERE order_id=? ORDER BY id", (o["id"],))
    out["next_statuses"] = [{"code": s, "label": osvc.STATUS_LABEL[s]} for s in osvc.TRANSITIONS.get(o["status"], [])
                            if not (o["payment_method"] != "cod" and o["status"] == "placed")]
    from ..security import has_perm
    if not has_perm(ctx.user, "finance"):
        out.pop("cost_total", None)
        for i in out["items"]:
            i.pop("cost_price", None)
    return out


@api("POST", "/api/admin/orders/{oid:int}/status", auth="admin", perm="orders")
def admin_order_status(ctx):
    status = ctx.get("status")
    note = text(ctx.get("note"), "Note", required=False, max_len=300)
    if status in ("refund_processing", "refunded"):
        from ..security import has_perm
        if not has_perm(ctx.user, "returns"):
            raise ApiError(403, "Refunds need the Returns permission.")
    db = get_db()
    order = db.one("SELECT * FROM orders WHERE id=?", (ctx.params["oid"],))
    if not order:
        raise ApiError(404, "Order not found.")
    if status == "refunded":
        ref = text(ctx.get("reference"), "Refund reference", required=False, max_len=80)
        if order["payment_method"] == "razorpay":
            gw = psvc.refund_via_gateway(order)
            ref = ref or gw
        if ref:
            db.run("UPDATE refunds SET reference=? WHERE order_id=? AND status='processing'", (ref, order["id"]))
    o = osvc.change_status(order["id"], status, ctx.user, note, restock=ctx.get("restock", True) is not False)
    audit(ctx.uid, "order_status", "order", o["order_no"], f"{order['status']} → {status}", ctx.ip)
    return osvc.serialize_order(db, o, admin=True)


@api("PUT", "/api/admin/orders/{oid:int}/shipping", auth="admin", perm="orders")
def admin_order_shipping(ctx):
    db = get_db()
    o = db.one("SELECT * FROM orders WHERE id=?", (ctx.params["oid"],))
    if not o:
        raise ApiError(404, "Order not found.")
    d = {"courier": text(ctx.get("courier"), "Courier", required=False, max_len=60),
         "tracking_no": text(ctx.get("tracking_no"), "Tracking number", required=False, max_len=60)}
    for k in ("est_delivery_from", "est_delivery_to"):
        v = ctx.get(k)
        if v:
            try:
                date.fromisoformat(v)
            except ValueError:
                raise ApiError(400, "Invalid date.")
        d[k] = v or o[k]
    d["updated_at"] = now_iso()
    db.update("orders", o["id"], d)
    if d["tracking_no"] and d["tracking_no"] != o["tracking_no"]:
        osvc.add_event(db, o["id"], o["status"], f"Shipment details: {d['courier'] or 'Courier'} · {d['tracking_no']}", ctx.uid)
        notify(o["user_id"], f"Tracking updated for {o['order_no']}", f"{d['courier'] or 'Courier'} tracking number {d['tracking_no']}",
               f"#/order/{o['order_no']}")
    audit(ctx.uid, "order_shipping", "order", o["order_no"], jdump(d), ctx.ip)
    return osvc.serialize_order(db, db.one("SELECT * FROM orders WHERE id=?", (o["id"],)), admin=True)


@api("POST", "/api/admin/orders/{oid:int}/collect-cash", auth="admin", perm="orders")
def collect_cash(ctx):
    db = get_db()
    with transaction(db):
        o = db.one("SELECT * FROM orders WHERE id=?", (ctx.params["oid"],))
        if not o:
            raise ApiError(404, "Order not found.")
        if o["payment_method"] != "cod":
            raise ApiError(400, "Only Cash-on-Delivery orders can be marked as cash collected. Online payments are verified by the gateway.")
        if o["payment_status"] == "paid":
            raise ApiError(400, "Cash has already been recorded for this order.")
        if o["status"] not in ("out_for_delivery", "delivered"):
            raise ApiError(400, "Record cash only when the order is out for delivery or delivered.")
        osvc.mark_paid(db, o, f"Cash collected (recorded by {ctx.user['name']})")
        db.insert("payments", {"order_id": o["id"], "method": "cod", "amount": o["grand_total"], "status": "verified",
                               "provider_payment_id": f"CASH-{ctx.uid}", "created_at": now_iso(), "verified_at": now_iso()})
    audit(ctx.uid, "cod_collected", "order", o["order_no"], str(o["grand_total"]), ctx.ip)
    return osvc.serialize_order(db, db.one("SELECT * FROM orders WHERE id=?", (o["id"],)), admin=True)


@api("POST", "/api/admin/orders/{oid:int}/upi-review", auth="admin", perm="orders")
def upi_review(ctx):
    from ..services import payments as psvc
    db = get_db()
    o = db.one("SELECT * FROM orders WHERE id=?", (ctx.params["oid"],))
    if not o:
        raise ApiError(404, "Order not found.")
    action = ctx.get("action")
    o = psvc.review_upi(o, ctx.user, action, text(ctx.get("note"), "Note", required=False, max_len=200))
    audit(ctx.uid, f"upi_{action}", "order", o["order_no"], str(o["grand_total"]), ctx.ip)
    return osvc.serialize_order(db, db.one("SELECT * FROM orders WHERE id=?", (o["id"],)), admin=True)


# ================================================================ returns & refunds
@api("GET", "/api/admin/returns", auth="admin", perm="returns")
def returns_list(ctx):
    db = get_db()
    st = ctx.q("status", "pending")
    rows = db.all("SELECT r.*, o.order_no, o.grand_total, o.status AS order_status, o.payment_status, o.payment_method, u.name AS customer "
                  "FROM return_requests r JOIN orders o ON o.id=r.order_id JOIN users u ON u.id=r.user_id "
                  + ("WHERE r.status=? " if st != "all" else "") + "ORDER BY r.id DESC LIMIT 200", (st,) if st != "all" else ())
    for r in rows:
        r["order_status_label"] = osvc.STATUS_LABEL[r["order_status"]]
    refunds = db.all("SELECT f.*, o.order_no, u.name AS customer FROM refunds f JOIN orders o ON o.id=f.order_id JOIN users u ON u.id=o.user_id "
                     "ORDER BY f.id DESC LIMIT 200")
    return {"requests": rows, "refunds": refunds}


@api("POST", "/api/admin/returns/{rid:int}/resolve", auth="admin", perm="returns")
def resolve_return(ctx):
    db = get_db()
    r = db.one("SELECT * FROM return_requests WHERE id=?", (ctx.params["rid"],))
    if not r or r["status"] != "pending":
        raise ApiError(400, "This request is not pending.")
    action = ctx.get("action")
    note = text(ctx.get("note"), "Note", required=False, max_len=300)
    order = db.one("SELECT * FROM orders WHERE id=?", (r["order_id"],))
    if action == "approve":
        if r["kind"] == "cancel":
            osvc.change_status(order["id"], "cancelled", ctx.user, note or "Cancellation approved")
        else:
            osvc.change_status(order["id"], "return_in_progress", ctx.user, note or "Return approved — pickup will be arranged")
        db.run("UPDATE return_requests SET status='approved', resolution_note=?, restock=?, resolved_at=? WHERE id=?",
               (note, 0 if ctx.get("restock") is False else 1, now_iso(), r["id"]))
    elif action == "reject":
        with transaction(db):
            db.run("UPDATE orders SET status=?, updated_at=? WHERE id=?", (r["prev_status"], now_iso(), order["id"]))
            osvc.add_event(db, order["id"], r["prev_status"], f"{'Cancellation' if r['kind']=='cancel' else 'Return'} request declined"
                           + (f": {note}" if note else ""), ctx.uid)
            db.run("UPDATE return_requests SET status='rejected', resolution_note=?, resolved_at=? WHERE id=?", (note, now_iso(), r["id"]))
        notify(order["user_id"], f"Request declined for {order['order_no']}", note or "Your request could not be approved.",
               f"#/order/{order['order_no']}")
    else:
        raise ApiError(400, "Choose approve or reject.")
    audit(ctx.uid, f"{r['kind']}_{action}", "order", order["order_no"], note, ctx.ip)
    return {"ok": True}


# ================================================================ customers
EXCL = ",".join(f"'{s}'" for s in osvc.SALE_EXCLUDED)


@api("GET", "/api/admin/customers", auth="admin", perm="customers")
def customers(ctx):
    db = get_db()
    where, params = ["u.role='customer'"], []
    if ctx.q("q"):
        where.append("(LOWER(u.name) LIKE ? OR LOWER(u.email) LIKE ? OR u.phone LIKE ? OR LOWER(b.code) LIKE ?)")
        params += [_like(ctx.q("q"))] * 4
    if ctx.q("status"):
        where.append("u.status=?"); params.append(ctx.q("status"))
    if ctx.q("company"):
        where.append("b.company_code=?"); params.append(ctx.q("company"))
    w = " AND ".join(where)
    total = db.val(f"SELECT COUNT(*) FROM users u LEFT JOIN buyers b ON b.id=u.buyer_id WHERE {w}", params)
    page, per, off = page_args(ctx, 25, 200)
    sort = {"spent": "spent DESC", "orders": "orders DESC", "recent": "last_order DESC", "name": "u.name"}.get(ctx.q("sort"), "u.created_at DESC")
    rows = db.all(f"SELECT u.id, u.name, u.email, u.phone, u.status, u.created_at, u.is_sample, b.code AS buyer_code, "
                  f"(SELECT COUNT(*) FROM orders o WHERE o.user_id=u.id) AS orders, "
                  f"(SELECT COALESCE(SUM(grand_total),0) FROM orders o WHERE o.user_id=u.id AND o.status NOT IN ({EXCL})) AS spent, "
                  f"(SELECT MAX(created_at) FROM orders o WHERE o.user_id=u.id) AS last_order "
                  f"FROM users u LEFT JOIN buyers b ON b.id=u.buyer_id WHERE {w} ORDER BY {sort} LIMIT {per} OFFSET {off}", params)
    for r in rows:
        r["spent"] = money(r["spent"])
    return {"items": rows, "total": total, "page": page, "per": per}


@api("GET", "/api/admin/customers/{uid:int}", auth="admin", perm="customers")
def customer_detail(ctx):
    db = get_db()
    u = db.one("SELECT u.id, u.name, u.email, u.phone, u.status, u.created_at, u.last_login_at, u.is_sample, u.buyer_id, "
               "b.code AS buyer_code FROM users u LEFT JOIN buyers b ON b.id=u.buyer_id WHERE u.id=? AND u.role='customer'", (ctx.params["uid"],))
    if not u:
        raise ApiError(404, "Customer not found.")
    orders = db.all("SELECT id, order_no, status, grand_total, payment_method, payment_status, created_at FROM orders WHERE user_id=? "
                    "ORDER BY created_at DESC", (u["id"],))
    for o in orders:
        o["status_label"] = osvc.STATUS_LABEL[o["status"]]
    valid = [o for o in orders if o["status"] not in osvc.SALE_EXCLUDED]
    top = db.all(f"SELECT i.name, SUM(i.qty) AS units, COUNT(DISTINCT o.id) AS times FROM order_items i JOIN orders o ON o.id=i.order_id "
                 f"WHERE o.user_id=? AND o.status NOT IN ({EXCL}) GROUP BY i.name ORDER BY units DESC LIMIT 5", (u["id"],))
    return {
        **u, "addresses": db.all("SELECT * FROM addresses WHERE user_id=? ORDER BY is_default DESC", (u["id"],)),
        "orders": orders, "total_orders": len(orders), "total_spent": money(sum(o["grand_total"] for o in valid)),
        "last_order": orders[0]["created_at"] if orders else None,
        "current_orders": [o for o in orders if o["status"] in osvc.OPEN_STATUSES],
        "cancelled_orders": [o for o in orders if o["status"] == "cancelled"],
        "returns": db.all("SELECT r.kind, r.reason, r.status, r.created_at, o.order_no FROM return_requests r JOIN orders o ON o.id=r.order_id "
                          "WHERE r.user_id=? ORDER BY r.id DESC", (u["id"],)),
        "refunds": db.all("SELECT f.amount, f.status, f.reference, f.created_at, o.order_no FROM refunds f JOIN orders o ON o.id=f.order_id "
                          "WHERE o.user_id=? ORDER BY f.id DESC", (u["id"],)),
        "top_products": top,
    }


@api("PUT", "/api/admin/customers/{uid:int}", auth="admin", perm="customers")
def customer_update(ctx):
    db = get_db()
    uid = ctx.params["uid"]
    u = db.one("SELECT * FROM users WHERE id=? AND role='customer'", (uid,))
    if not u:
        raise ApiError(404, "Customer not found.")
    if "status" in ctx.body:
        st = ctx.get("status")
        if st not in ("active", "suspended"):
            raise ApiError(400, "Invalid status.")
        db.run("UPDATE users SET status=? WHERE id=?", (st, uid))
        if st == "suspended":
            destroy_user_sessions(uid)
        audit(ctx.uid, "customer_status", "user", uid, st, ctx.ip)
    if "buyer_code" in ctx.body:
        from ..security import has_perm
        if not has_perm(ctx.user, "buyers"):
            raise ApiError(403, "Assigning buyer codes needs the Unit buyers permission.")
        code = (ctx.get("buyer_code") or "").strip().upper()
        with transaction(db):
            db.run("UPDATE buyers SET user_id=NULL WHERE user_id=?", (uid,))
            if code:
                b = db.one("SELECT * FROM buyers WHERE code=? AND active=1", (code,))
                if not b:
                    raise ApiError(404, "Buyer code not found or inactive.")
                if b["user_id"] and b["user_id"] != uid:
                    raise ApiError(409, "That buyer code is already linked to another account.")
                db.run("UPDATE buyers SET user_id=? WHERE id=?", (uid, b["id"]))
                db.run("UPDATE users SET buyer_id=? WHERE id=?", (b["id"], uid))
            else:
                db.run("UPDATE users SET buyer_id=NULL WHERE id=?", (uid,))
        audit(ctx.uid, "customer_buyer_code", "user", uid, code or "(none)", ctx.ip)
    return {"ok": True}


# ================================================================ unit buyers
@api("GET", "/api/admin/buyers", auth="admin", perm="buyers")
def buyers(ctx):
    db = get_db()
    where, params = ["1=1"], []
    if ctx.q("company"):
        where.append("b.company_code=?"); params.append(ctx.q("company"))
    if ctx.q("category"):
        where.append("b.category_code=?"); params.append(ctx.q("category"))
    if ctx.q("q"):
        where.append("(LOWER(b.code) LIKE ? OR LOWER(b.real_name) LIKE ?)"); params += [_like(ctx.q("q"))] * 2
    w = " AND ".join(where)
    rows = db.all(f"SELECT b.*, u.name AS account_name, u.email AS account_email, "
                  f"(SELECT COUNT(*) FROM orders o WHERE o.buyer_code=b.code AND o.status NOT IN ({EXCL})) AS orders, "
                  f"(SELECT COALESCE(SUM(grand_total),0) FROM orders o WHERE o.buyer_code=b.code AND o.status NOT IN ({EXCL})) AS spent "
                  f"FROM buyers b LEFT JOIN users u ON u.id=b.user_id WHERE {w} ORDER BY b.company_code, b.category_code, b.seniority", params)
    return {"items": rows, "companies": db.all("SELECT * FROM companies ORDER BY sort, code"),
            "categories": db.all("SELECT * FROM rank_categories ORDER BY sort, code")}


def _validate_buyer(db, company, category, seniority, existing_id=None):
    if not db.one("SELECT id FROM companies WHERE code=?", (company,)):
        raise ApiError(400, f"Unknown company code '{company}'.")
    if not db.one("SELECT id FROM rank_categories WHERE code=?", (category,)):
        raise ApiError(400, f"Unknown category code '{category}'.")
    code = f"{company}-{category}-{seniority}"
    clash = db.one("SELECT id FROM buyers WHERE code=?", (code,))
    if clash and clash["id"] != existing_id:
        raise ApiError(409, f"Buyer code {code} already exists.")
    return code


@api("POST", "/api/admin/buyers", auth="admin", perm="buyers")
def add_buyer(ctx):
    db = get_db()
    company = text(ctx.get("company_code"), "Company", max_len=4).upper()
    category = text(ctx.get("category_code"), "Category", max_len=4).upper()
    sen = int(num(ctx.get("seniority"), "Seniority", 1, 999, integer=True))
    code = _validate_buyer(db, company, category, sen)
    bid = db.insert("buyers", {"code": code, "company_code": company, "category_code": category, "seniority": sen,
                               "real_name": text(ctx.get("real_name"), "Name", required=False, max_len=80), "active": 1,
                               "created_at": now_iso()})
    audit(ctx.uid, "buyer_create", "buyer", code, None, ctx.ip)
    return db.one("SELECT * FROM buyers WHERE id=?", (bid,))


@api("PUT", "/api/admin/buyers/{bid:int}", auth="admin", perm="buyers")
def edit_buyer(ctx):
    db = get_db()
    b = db.one("SELECT * FROM buyers WHERE id=?", (ctx.params["bid"],))
    if not b:
        raise ApiError(404, "Buyer not found.")
    d = {"real_name": text(ctx.get("real_name"), "Name", required=False, max_len=80), "active": 1 if ctx.get("active", True) else 0}
    db.update("buyers", b["id"], d)
    audit(ctx.uid, "buyer_update", "buyer", b["code"], None, ctx.ip)
    return db.one("SELECT * FROM buyers WHERE id=?", (b["id"],))


@api("DELETE", "/api/admin/buyers/{bid:int}", auth="admin", perm="buyers")
def delete_buyer(ctx):
    db = get_db()
    b = db.one("SELECT * FROM buyers WHERE id=?", (ctx.params["bid"],))
    if not b:
        raise ApiError(404, "Buyer not found.")
    if db.one("SELECT id FROM orders WHERE buyer_code=? LIMIT 1", (b["code"],)):
        db.update("buyers", b["id"], {"active": 0})
        return {"ok": True, "message": "Buyer has order history, so it was deactivated instead of deleted."}
    with transaction(db):
        db.run("UPDATE users SET buyer_id=NULL WHERE buyer_id=?", (b["id"],))
        db.run("DELETE FROM buyers WHERE id=?", (b["id"],))
    audit(ctx.uid, "buyer_delete", "buyer", b["code"], None, ctx.ip)
    return {"ok": True, "message": "Buyer deleted."}


def _parse_buyer_csv(db, csv_text):
    rows, errors, seen = [], [], set()
    reader = csv.DictReader(io.StringIO(csv_text.strip().lstrip("﻿")))
    fields = [f.strip().lower() for f in (reader.fieldnames or [])]
    need = {"company", "category", "seniority"}
    if not need.issubset(fields):
        raise ApiError(400, "CSV header must include: company, category, seniority (and optionally name).")
    for n, raw in enumerate(reader, start=2):
        r = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        comp, cat, sen, name = r.get("company", "").upper(), r.get("category", "").upper(), r.get("seniority", ""), r.get("name", "")
        problem = None
        if not db.one("SELECT id FROM companies WHERE code=?", (comp,)):
            problem = f"unknown company '{comp}'"
        elif not db.one("SELECT id FROM rank_categories WHERE code=?", (cat,)):
            problem = f"unknown category '{cat}'"
        elif not sen.isdigit() or not (1 <= int(sen) <= 999):
            problem = "seniority must be a number 1-999"
        code = f"{comp}-{cat}-{sen}"
        status = "new"
        if not problem:
            if code in seen:
                problem = "duplicate row in file"
            elif db.one("SELECT id FROM buyers WHERE code=?", (code,)):
                status = "update"
        seen.add(code)
        if problem:
            errors.append({"line": n, "error": problem, "row": r})
        else:
            rows.append({"line": n, "code": code, "company_code": comp, "category_code": cat, "seniority": int(sen),
                         "real_name": name[:80] or None, "action": status})
        if n > 5000:
            raise ApiError(400, "CSV is limited to 5000 rows.")
    return rows, errors


@api("POST", "/api/admin/buyers/import/preview", auth="admin", perm="buyers")
def buyers_preview(ctx):
    rows, errors = _parse_buyer_csv(get_db(), text(ctx.get("csv"), "CSV", max_len=1_000_000))
    return {"rows": rows, "errors": errors, "new": sum(1 for r in rows if r["action"] == "new"),
            "updates": sum(1 for r in rows if r["action"] == "update")}


@api("POST", "/api/admin/buyers/import/commit", auth="admin", perm="buyers")
def buyers_commit(ctx):
    db = get_db()
    rows, errors = _parse_buyer_csv(db, text(ctx.get("csv"), "CSV", max_len=1_000_000))
    if errors:
        raise ApiError(400, f"Fix {len(errors)} error(s) before importing.", {"errors": errors})
    with transaction(db):
        for r in rows:
            if r["action"] == "new":
                db.insert("buyers", {k: r[k] for k in ("code", "company_code", "category_code", "seniority", "real_name")} |
                          {"active": 1, "created_at": now_iso()})
            elif r["real_name"]:
                db.run("UPDATE buyers SET real_name=? WHERE code=?", (r["real_name"], r["code"]))
    audit(ctx.uid, "buyers_import", "buyer", None, f"{len(rows)} rows", ctx.ip)
    return {"ok": True, "imported": len(rows)}


@api("POST", "/api/admin/companies", auth="admin", perm="buyers")
def add_company(ctx):
    db = get_db()
    code = text(ctx.get("code"), "Code", max_len=3).upper()
    if not re.fullmatch(r"[A-Z]{1,3}", code):
        raise ApiError(400, "Company code must be 1-3 letters.")
    if db.one("SELECT id FROM companies WHERE code=?", (code,)):
        raise ApiError(409, "Company code already exists.")
    db.insert("companies", {"code": code, "name": text(ctx.get("name"), "Name", max_len=40),
                            "sort": db.val("SELECT COALESCE(MAX(sort),0)+1 FROM companies"), "active": 1})
    return {"ok": True}


@api("POST", "/api/admin/rank-categories", auth="admin", perm="buyers")
def add_rank(ctx):
    db = get_db()
    code = text(ctx.get("code"), "Code", max_len=3).upper()
    if not re.fullmatch(r"[A-Z]{1,3}", code):
        raise ApiError(400, "Category code must be 1-3 letters.")
    if db.one("SELECT id FROM rank_categories WHERE code=?", (code,)):
        raise ApiError(409, "Category code already exists.")
    db.insert("rank_categories", {"code": code, "name": text(ctx.get("name"), "Name", max_len=40),
                                  "sort": db.val("SELECT COALESCE(MAX(sort),0)+1 FROM rank_categories")})
    return {"ok": True}


# ================================================================ analytics
@api("GET", "/api/admin/analytics/insights", auth="admin", perm="analytics")
def ai_insights(ctx):
    data = analytics.insights()
    from ..security import has_perm
    data["ai_configured"] = bool(config.ANTHROPIC_API_KEY)
    if not has_perm(ctx.user, "finance"):
        for r in data["products"]:
            r.pop("gross_margin_pct", None)
    return data


@api("GET", "/api/admin/analytics/forecast", auth="admin", perm="analytics")
def ai_forecast(ctx):
    scope = ctx.q("scope", "all")
    ref = ctx.qint("id")
    return analytics.forecast(scope if scope in ("all", "category", "product") else "all", ref, ctx.qint("horizon", 30),
                              "units" if ctx.q("metric") == "units" else "revenue")


@api("POST", "/api/admin/analytics/narrative", auth="admin", perm="analytics", limit="review")
def ai_narr(ctx):
    return analytics.ai_narrative(analytics.insights())


# ================================================================ reports & exports
@api("GET", "/api/admin/reports/grouped", auth="admin", perm="reports")
def report_grouped(ctx):
    return reports.grouped_report(ctx.q("group", "company"), ctx.q("range", "30d"), ctx.q("from"), ctx.q("to"))


@api("GET", "/api/admin/export/{kind}", auth="admin", perm="reports")
def export(ctx):
    kind = ctx.params["kind"].replace(".csv", "")
    from ..security import has_perm
    if kind == "customers" and not has_perm(ctx.user, "customers"):
        raise ApiError(403, "Customer exports need the Customers permission.")
    body, fname = reports.export(kind, ctx.q("range", "30d"), ctx.q("from"), ctx.q("to"))
    audit(ctx.uid, "export", kind, None, fname, ctx.ip)
    return Response(body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ================================================================ finance
@api("GET", "/api/admin/finance", auth="admin", perm="finance")
def finance(ctx):
    db = get_db()
    a, b = reports.resolve_range(ctx.q("range", "month"), ctx.q("from"), ctx.q("to"))
    ov = reports.overview("custom", str(a), str(b))
    exp = db.all("SELECT * FROM expenses WHERE date >= ? AND date <= ? ORDER BY date DESC, id DESC", (str(a), str(b)))
    by_cat = {}
    for e in exp:
        by_cat[e["category"]] = money(by_cat.get(e["category"], 0) + e["amount"])
    s, e = reports._bounds(a, b)
    refunds = db.one("SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS amt FROM refunds WHERE created_at >= ? AND created_at < ?", (s, e))
    return {"range": ov["range"], "sales": ov["sales"], "expenses": exp, "expenses_by_category": by_cat,
            "refunds": {"count": refunds["n"], "amount": money(refunds["amt"])}, "series": ov["series"]}


@api("POST", "/api/admin/expenses", auth="admin", perm="finance")
def add_expense(ctx):
    db = get_db()
    d = ctx.get("date")
    try:
        date.fromisoformat(d)
    except (TypeError, ValueError):
        raise ApiError(400, "Enter a valid date.")
    eid = db.insert("expenses", {"date": d, "category": text(ctx.get("category"), "Category", max_len=40),
                                 "amount": money(num(ctx.get("amount"), "Amount", 0.01, 100_000_000)),
                                 "note": text(ctx.get("note"), "Note", required=False, max_len=200), "created_at": now_iso()})
    audit(ctx.uid, "expense_add", "expense", eid, None, ctx.ip)
    return {"ok": True}


@api("DELETE", "/api/admin/expenses/{eid:int}", auth="admin", perm="finance")
def delete_expense(ctx):
    get_db().run("DELETE FROM expenses WHERE id=?", (ctx.params["eid"],))
    audit(ctx.uid, "expense_delete", "expense", ctx.params["eid"], None, ctx.ip)
    return {"ok": True}


# ================================================================ marketing
@api("GET", "/api/admin/banners", auth="admin", perm="marketing")
def banners(ctx):
    return {"items": get_db().all("SELECT * FROM banners ORDER BY sort, id"), "announcement": get_settings()["announcement"]}


def _banner_fields(ctx):
    theme = ctx.get("theme", "navy")
    if theme not in ("navy", "teal", "coral", "gold", "plum", "slate"):
        raise ApiError(400, "Unknown banner theme.")
    link = text(ctx.get("link"), "Link", required=False, max_len=200)
    if link and not (link.startswith("#/") or link.startswith("/")):
        raise ApiError(400, "Banner links must be internal (start with #/).")
    return {"title": text(ctx.get("title"), "Title", max_len=80), "subtitle": text(ctx.get("subtitle"), "Subtitle", required=False, max_len=160),
            "cta": text(ctx.get("cta"), "Button text", required=False, max_len=30), "link": link, "theme": theme,
            "department": text(ctx.get("department"), "Department", required=False, max_len=40),
            "active": 1 if ctx.get("active", True) else 0, "sort": int(num(ctx.get("sort", 0), "Order", integer=True, required=False) or 0),
            "placement": "hero"}


@api("POST", "/api/admin/banners", auth="admin", perm="marketing")
def add_banner(ctx):
    db = get_db()
    bid = db.insert("banners", {**_banner_fields(ctx), "created_at": now_iso()})
    audit(ctx.uid, "banner_create", "banner", bid, None, ctx.ip)
    return {"ok": True}


@api("PUT", "/api/admin/banners/{bid:int}", auth="admin", perm="marketing")
def edit_banner(ctx):
    get_db().update("banners", ctx.params["bid"], _banner_fields(ctx))
    return {"ok": True}


@api("DELETE", "/api/admin/banners/{bid:int}", auth="admin", perm="marketing")
def delete_banner(ctx):
    get_db().run("DELETE FROM banners WHERE id=?", (ctx.params["bid"],))
    audit(ctx.uid, "banner_delete", "banner", ctx.params["bid"], None, ctx.ip)
    return {"ok": True}


@api("PUT", "/api/admin/announcement", auth="admin", perm="marketing")
def set_announcement(ctx):
    set_settings({"announcement": text(ctx.get("announcement"), "Announcement", required=False, max_len=160) or ""})
    return {"ok": True}


@api("GET", "/api/admin/coupons", auth="admin", perm="marketing")
def coupons(ctx):
    return {"items": get_db().all("SELECT * FROM coupons ORDER BY id DESC")}


def _coupon_fields(ctx):
    kind = ctx.get("kind", "pct")
    if kind not in ("pct", "flat"):
        raise ApiError(400, "Coupon type must be percentage or flat.")
    value = num(ctx.get("value"), "Value", 0.01, 100 if kind == "pct" else 1_000_000)
    code = text(ctx.get("code"), "Code", max_len=20).upper()
    if not re.fullmatch(r"[A-Z0-9]{3,20}", code):
        raise ApiError(400, "Coupon code must be 3-20 letters or numbers.")
    def _d(k):
        v = ctx.get(k)
        if not v:
            return None
        try:
            date.fromisoformat(v[:10])
        except ValueError:
            raise ApiError(400, "Invalid date.")
        return v[:10] + ("T00:00:00" if k == "starts_at" else "T23:59:59")
    return {"code": code, "description": text(ctx.get("description"), "Description", required=False, max_len=120), "kind": kind,
            "value": value, "min_order": num(ctx.get("min_order", 0), "Minimum order", 0, required=False) or 0,
            "max_discount": num(ctx.get("max_discount"), "Max discount", 0, required=False),
            "usage_limit": num(ctx.get("usage_limit"), "Usage limit", 1, integer=True, required=False),
            "starts_at": _d("starts_at"), "ends_at": _d("ends_at"), "active": 1 if ctx.get("active", True) else 0}


@api("POST", "/api/admin/coupons", auth="admin", perm="marketing")
def add_coupon(ctx):
    db = get_db()
    d = _coupon_fields(ctx)
    if db.one("SELECT id FROM coupons WHERE code=?", (d["code"],)):
        raise ApiError(409, "Coupon code already exists.")
    db.insert("coupons", {**d, "created_at": now_iso()})
    audit(ctx.uid, "coupon_create", "coupon", d["code"], None, ctx.ip)
    return {"ok": True}


@api("PUT", "/api/admin/coupons/{cid:int}", auth="admin", perm="marketing")
def edit_coupon(ctx):
    db = get_db()
    d = _coupon_fields(ctx)
    clash = db.one("SELECT id FROM coupons WHERE code=?", (d["code"],))
    if clash and clash["id"] != ctx.params["cid"]:
        raise ApiError(409, "Coupon code already exists.")
    db.update("coupons", ctx.params["cid"], d)
    return {"ok": True}


@api("DELETE", "/api/admin/coupons/{cid:int}", auth="admin", perm="marketing")
def delete_coupon(ctx):
    get_db().run("DELETE FROM coupons WHERE id=?", (ctx.params["cid"],))
    return {"ok": True}


# ================================================================ staff (owner only)
@api("GET", "/api/admin/staff", auth="owner")
def staff(ctx):
    rows = get_db().all("SELECT id, name, email, phone, role, permissions, status, created_at, last_login_at FROM users "
                        "WHERE role IN ('owner','staff') ORDER BY role DESC, id")
    for r in rows:
        r["permissions"] = jload(r["permissions"], [])
    return {"items": rows, "permissions": PERMISSIONS}


def _perms(ctx):
    perms = ctx.get("permissions") or []
    if not isinstance(perms, list) or any(p not in PERMISSIONS for p in perms):
        raise ApiError(400, "Invalid permissions.")
    return perms


@api("POST", "/api/admin/staff", auth="owner")
def add_staff(ctx):
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
    sid = db.insert("users", {"name": text(ctx.get("name"), "Name", max_len=80), "email": email,
                              "phone": text(ctx.get("phone"), "Phone", required=False, max_len=16),
                              "password_hash": hash_password(pw), "role": "staff", "permissions": jdump(_perms(ctx)),
                              "status": "active", "created_at": now_iso()})
    audit(ctx.uid, "staff_create", "user", sid, email, ctx.ip)
    return {"ok": True}


@api("PUT", "/api/admin/staff/{sid:int}", auth="owner")
def edit_staff(ctx):
    db = get_db()
    s = db.one("SELECT * FROM users WHERE id=? AND role='staff'", (ctx.params["sid"],))
    if not s:
        raise ApiError(404, "Staff member not found.")
    d = {"permissions": jdump(_perms(ctx)), "name": text(ctx.get("name"), "Name", max_len=80)}
    st = ctx.get("status", s["status"])
    if st not in ("active", "suspended"):
        raise ApiError(400, "Invalid status.")
    d["status"] = st
    if ctx.get("password"):
        prob = password_problem(ctx.get("password"))
        if prob:
            raise ApiError(400, prob)
        d["password_hash"] = hash_password(ctx.get("password"))
    db.update("users", s["id"], d)
    destroy_user_sessions(s["id"])  # force re-login so new permissions apply immediately
    audit(ctx.uid, "staff_update", "user", s["id"], jdump({"status": st, "permissions": _perms(ctx)}), ctx.ip)
    return {"ok": True}


# ================================================================ settings (owner only)
@api("GET", "/api/admin/settings", auth="owner")
def settings(ctx):
    db = get_db()
    return {"settings": get_settings(), "delivery_methods": db.all("SELECT * FROM delivery_methods ORDER BY sort, id"),
            "integrations": {
                "database": "PostgreSQL" if IS_PG else "SQLite (local file)",
                "razorpay": "Configured" if config.razorpay_configured() else "Not configured — add RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET to .env",
                "razorpay_webhook": "Configured" if config.RAZORPAY_WEBHOOK_SECRET else "Not configured (optional)",
                "ai_narrative": "Configured" if config.ANTHROPIC_API_KEY else "Not configured (optional) — statistical analytics active",
                "email": f"Configured ({_mailer.provider_name()})" if _mailer.configured() else "Not configured — in-app notifications only; login codes are printed in the server log",
                "courier_api": "Not configured — enter courier & tracking numbers manually on each order",
            },
            "sample_counts": {
                "products": db.val("SELECT COUNT(*) FROM products WHERE is_sample=1"),
                "orders": db.val("SELECT COUNT(*) FROM orders WHERE is_sample=1"),
                "customers": db.val("SELECT COUNT(*) FROM users WHERE is_sample=1 AND role='customer'"),
            }}


@api("PUT", "/api/admin/settings", auth="owner")
def save_settings(ctx):
    vals = ctx.get("settings") or {}
    clean = {}
    for k, v in vals.items():
        if k not in DEFAULT_SETTINGS:
            continue
        default = DEFAULT_SETTINGS[k]
        if isinstance(default, bool):
            clean[k] = bool(v)
        elif isinstance(default, (int, float)):
            clean[k] = num(v, k.replace("_", " "), lo=0)
            if isinstance(default, int) and not isinstance(default, bool):
                clean[k] = int(clean[k])
        else:
            clean[k] = text(v, k.replace("_", " "), required=False, max_len=2000) or ""
    if "upi_id" in clean:
        clean["upi_id"] = clean["upi_id"].strip()
        if clean["upi_id"] and not re.fullmatch(r"[A-Za-z0-9._\-]{2,256}@[A-Za-z][A-Za-z0-9]{1,63}", clean["upi_id"]):
            raise ApiError(400, "Enter a valid UPI ID, for example yourname@okhdfcbank or 9876543210@ybl.")
    if clean.get("upi_enabled") and not (clean.get("upi_id") if "upi_id" in clean else get_settings().get("upi_id")):
        raise ApiError(400, "Enter your UPI ID before turning on UPI payments.")
    if "payment_expiry_minutes" in clean and not 5 <= clean["payment_expiry_minutes"] <= 1440:
        raise ApiError(400, "Payment expiry must be between 5 and 1440 minutes.")
    set_settings(clean)
    audit(ctx.uid, "settings_update", "settings", None, ",".join(clean.keys()), ctx.ip)
    return {"ok": True, "settings": get_settings()}


def _dm_fields(ctx):
    code = text(ctx.get("code"), "Code", max_len=20).lower()
    if not re.fullmatch(r"[a-z0-9_]+", code):
        raise ApiError(400, "Code may contain lowercase letters, numbers and underscores.")
    lo = int(num(ctx.get("eta_min_days", 2), "Min days", 0, 60, integer=True))
    hi = int(num(ctx.get("eta_max_days", 5), "Max days", 0, 90, integer=True))
    if hi < lo:
        raise ApiError(400, "Max days must be ≥ min days.")
    return {"code": code, "name": text(ctx.get("name"), "Name", max_len=40),
            "description": text(ctx.get("description"), "Description", required=False, max_len=120),
            "charge": money(num(ctx.get("charge", 0), "Charge", 0, 100000)),
            "free_above": num(ctx.get("free_above"), "Free above", 0, required=False),
            "eta_min_days": lo, "eta_max_days": hi, "active": 1 if ctx.get("active", True) else 0,
            "sort": int(num(ctx.get("sort", 0), "Sort", integer=True, required=False) or 0)}


@api("POST", "/api/admin/delivery-methods", auth="owner")
def add_dm(ctx):
    db = get_db()
    d = _dm_fields(ctx)
    if db.one("SELECT id FROM delivery_methods WHERE code=?", (d["code"],)):
        raise ApiError(409, "Code already exists.")
    db.insert("delivery_methods", d)
    return {"ok": True}


@api("PUT", "/api/admin/delivery-methods/{did:int}", auth="owner")
def edit_dm(ctx):
    db = get_db()
    d = _dm_fields(ctx)
    clash = db.one("SELECT id FROM delivery_methods WHERE code=?", (d["code"],))
    if clash and clash["id"] != ctx.params["did"]:
        raise ApiError(409, "Code already exists.")
    if not d["active"] and db.val("SELECT COUNT(*) FROM delivery_methods WHERE active=1 AND id<>?", (ctx.params["did"],)) == 0:
        raise ApiError(400, "At least one delivery method must stay active.")
    db.update("delivery_methods", ctx.params["did"], d)
    return {"ok": True}


@api("POST", "/api/admin/settings/clear-sample-data", auth="owner")
def clear_sample(ctx):
    if ctx.get("confirm") != "DELETE SAMPLE DATA":
        raise ApiError(400, "Type DELETE SAMPLE DATA to confirm.")
    db = get_db()
    with transaction(db):
        sample_orders = [r["id"] for r in db.all("SELECT id FROM orders WHERE is_sample=1")]
        for oid in sample_orders:
            db.run("DELETE FROM order_items WHERE order_id=?", (oid,))
            db.run("DELETE FROM order_events WHERE order_id=?", (oid,))
            db.run("DELETE FROM payments WHERE order_id=?", (oid,))
            db.run("DELETE FROM refunds WHERE order_id=?", (oid,))
            db.run("DELETE FROM return_requests WHERE order_id=?", (oid,))
        db.run("DELETE FROM orders WHERE is_sample=1")
        sample_users = [r["id"] for r in db.all("SELECT id FROM users WHERE is_sample=1 AND role IN ('customer','staff')")]
        for uid in sample_users:
            if db.one("SELECT id FROM orders WHERE user_id=?", (uid,)):
                continue  # has real orders now: keep account
            db.run("UPDATE buyers SET user_id=NULL WHERE user_id=?", (uid,))
            db.run("DELETE FROM reviews WHERE user_id=?", (uid,))
            db.run("DELETE FROM users WHERE id=?", (uid,))
        for p in db.all("SELECT id FROM products WHERE is_sample=1"):
            if db.one("SELECT id FROM order_items WHERE product_id=?", (p["id"],)):
                db.run("UPDATE products SET status='inactive' WHERE id=?", (p["id"],))
            else:
                db.run("DELETE FROM products WHERE id=?", (p["id"],))
        db.run("DELETE FROM expenses WHERE is_sample=1")
        db.run("DELETE FROM buyers WHERE is_sample=1 AND user_id IS NULL AND code NOT IN (SELECT DISTINCT buyer_code FROM orders WHERE buyer_code IS NOT NULL)")
        db.run("DELETE FROM activity_daily WHERE product_id NOT IN (SELECT id FROM products)")
        db.run("DELETE FROM stock_events WHERE product_id NOT IN (SELECT id FROM products)")
        # recompute reservations from the orders that remain
        db.run("UPDATE products SET reserved_qty = COALESCE((SELECT SUM(i.qty) FROM order_items i JOIN orders o ON o.id=i.order_id "
               "WHERE i.product_id=products.id AND o.stock_state='reserved' AND o.status NOT IN ('cancelled')), 0)")
    audit(ctx.uid, "sample_data_cleared", "settings", None, f"{len(sample_orders)} orders", ctx.ip)
    return {"ok": True, "message": f"Removed {len(sample_orders)} sample orders and sample catalogue data."}


@api("GET", "/api/admin/audit", auth="owner")
def audit_log(ctx):
    page, per, off = page_args(ctx, 50, 200)
    db = get_db()
    rows = db.all(f"SELECT a.*, u.name AS actor FROM audit_log a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT {per} OFFSET {off}")
    return {"items": rows, "total": db.val("SELECT COUNT(*) FROM audit_log"), "page": page, "per": per}


# ================================================================ share / QR codes
def _lan_ips():
    import socket
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent; picks the outgoing interface
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    private = lambda ip: ip.startswith(("10.", "192.168.")) or (ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31)
    return [ip for ip in ips if private(ip)] or [ip for ip in ips if not ip.startswith("127.")]


TUNNEL_METRICS = "http://127.0.0.1:45678/quicktunnel"


def _tunnel_url():
    """If the 'online access' helper (Cloudflare quick tunnel) is running, ask it for its public address."""
    import json as _json
    import urllib.request
    try:
        with urllib.request.urlopen(TUNNEL_METRICS, timeout=0.6) as r:
            host = (_json.loads(r.read().decode()) or {}).get("hostname")
        return f"https://{host}" if host else None
    except Exception:
        return None


@api("GET", "/api/admin/share-info", auth="admin")
def share_info(ctx):
    db = get_db()
    host_seen = ctx.request.url.hostname or ""
    ips = _lan_ips()
    if host_seen and host_seen not in ("127.0.0.1", "localhost") and not host_seen.endswith(".trycloudflare.com") \
            and host_seen not in ips and re.fullmatch(r"[0-9.]+", host_seen):
        ips.insert(0, host_seen)
    s = get_settings()
    tunnel = None if config.PUBLIC_URL else _tunnel_url()
    public = config.PUBLIC_URL or tunnel or (s.get("public_url") or "").rstrip("/") or None
    risky = db.all("SELECT email FROM users WHERE is_sample=1 AND role='staff' AND status='active'")
    demo_customer = db.one("SELECT id FROM users WHERE email='customer@demo.local' AND status='active'")
    return {"port": config.PORT, "bound_host": config.HOST,
            "phones_can_connect": config.HOST not in ("127.0.0.1", "localhost"),
            "addresses": ips, "expo_port": 8081, "store_name": s["store_name"],
            "public_url": public, "public_source": "server" if config.PUBLIC_URL else ("tunnel" if tunnel else ("settings" if public else None)),
            "saved_public_url": s.get("public_url") or "",
            "warnings": {"sample_staff": [r["email"] for r in risky], "demo_customer": bool(demo_customer),
                         "sandbox_on": bool(s["sandbox_enabled"])}}


@api("PUT", "/api/admin/public-url", auth="owner")
def set_public_url(ctx):
    url = (ctx.get("public_url") or "").strip().rstrip("/")
    if url and not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:\d+)?(/[A-Za-z0-9._~\-/]*)?", url):
        raise ApiError(400, "Enter a web address like https://shop.example.com")
    set_settings({"public_url": url})
    audit(ctx.uid, "public_url_set", "settings", None, url, ctx.ip)
    return {"ok": True}
