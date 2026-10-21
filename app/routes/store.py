"""Customer-facing API: catalogue, cart, wishlist, checkout, orders, payments, reviews, account."""
from .. import config
from ..db import get_db, jload, local_today, now_iso, transaction
from ..web import ApiError, api, num, page_args, text
from ..services import orders as osvc
from ..services import payments as psvc
from ..services.common import (available, bump_activity, discount_pct, first_images, get_settings, log_search, money,
                               product_card, stock_label)

VISIBLE = "('active','out_of_stock')"


# ---------------------------------------------------------------- meta & home
def category_tree(db, only_active=True):
    rows = db.all("SELECT * FROM categories " + ("WHERE active=1 " if only_active else "") + "ORDER BY sort, name")
    counts = {r["cid"]: r["n"] for r in db.all(f"SELECT category_id AS cid, COUNT(*) AS n FROM products WHERE status IN {VISIBLE} GROUP BY category_id")}
    sub_counts = {r["cid"]: r["n"] for r in db.all(f"SELECT subcategory_id AS cid, COUNT(*) AS n FROM products WHERE status IN {VISIBLE} GROUP BY subcategory_id")}
    imgs = {}
    for r in db.all(f"SELECT p.category_id, MIN(i.url) AS url FROM products p JOIN product_images i ON i.product_id=p.id "
                    f"WHERE p.status IN {VISIBLE} GROUP BY p.category_id"):
        imgs[r["category_id"]] = r["url"]
    own = {r["category_id"]: r["url"] for r in db.all("SELECT category_id, url FROM category_images")}
    roots = []
    by_id = {}
    for r in rows:
        node = {"id": r["id"], "name": r["name"], "slug": r["slug"], "department": r["department"], "icon": r["icon"],
                "color": r["color"], "parent_id": r["parent_id"], "children": [],
                "count": counts.get(r["id"], 0) if not r["parent_id"] else sub_counts.get(r["id"], 0),
                "image": own.get(r["id"]) or imgs.get(r["id"])}
        by_id[r["id"]] = node
    for node in by_id.values():
        if node["parent_id"] and node["parent_id"] in by_id:
            by_id[node["parent_id"]]["children"].append(node)
        elif not node["parent_id"]:
            roots.append(node)
    return roots


@api("GET", "/api/meta")
def meta(ctx):
    db = get_db()
    s = get_settings()
    tree = category_tree(db)
    depts = []
    for c in tree:
        if c["department"] and c["department"] not in depts:
            depts.append(c["department"])
    return {
        "store": {k: s[k] for k in ("store_name", "tagline", "announcement", "support_email", "support_phone",
                                    "return_window_days", "policy_returns", "policy_shipping", "policy_privacy")},
        "departments": depts, "categories": tree,
        "google_client_id": config.GOOGLE_CLIENT_ID,
        "payments": {
            "cod": {"enabled": bool(s["cod_enabled"]), "max": s["cod_max_amount"]},
            "razorpay": {"enabled": bool(s["razorpay_enabled"] and config.razorpay_configured()),
                         "configured": config.razorpay_configured()},
            "sandbox": {"enabled": bool(s["sandbox_enabled"])},
            "upi": {"enabled": bool(s.get("upi_enabled") and s.get("upi_id"))},
        },
    }


@api("GET", "/api/home")
def home(ctx):
    db = get_db()
    dept = ctx.q("dept")
    where, params = f"p.status IN {VISIBLE}", []
    if dept:
        where += " AND c.department=?"
        params.append(dept)
    base = f"SELECT p.* FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE {where}"

    def section(order, limit=10, extra=""):
        rows = db.all(f"{base} {extra} ORDER BY {order} LIMIT {limit}", params)
        imgs = first_images([r["id"] for r in rows])
        return [product_card(r, imgs.get(r["id"])) for r in rows]

    if dept:
        banners = db.all("SELECT * FROM banners WHERE active=1 AND placement='hero' AND (department IS NULL OR department='' OR department=?) "
                         "ORDER BY sort, id", (dept,))
    else:
        banners = db.all("SELECT * FROM banners WHERE active=1 AND placement='hero' ORDER BY sort, id")
    vids = {r["banner_id"]: r["url"] for r in db.all("SELECT banner_id, url FROM banner_videos")}
    auds = {r["banner_id"]: r["url"] for r in db.all("SELECT banner_id, url FROM banner_audios")}
    for b in banners:
        b["video_url"] = vids.get(b["id"])
        b["audio_url"] = auds.get(b["id"])
    for b in banners:  # illustrate each banner with a product from the category it links to
        b["image_url"] = b["image_url"] or None
        if not b["image_url"] and b["link"] and b["link"].startswith("#/c/"):
            row = db.one(f"SELECT i.url FROM product_images i JOIN products p ON p.id=i.product_id JOIN categories c ON c.id IN (p.category_id, p.subcategory_id) "
                         f"WHERE c.slug=? AND p.status IN {VISIBLE} ORDER BY p.featured DESC, p.units_sold DESC, i.sort LIMIT 1", (b["link"][4:],))
            b["image_url"] = row["url"] if row else None
    # recommendations: for signed-in customers, items from categories they bought/viewed; else top rated
    rec = []
    if ctx.user and ctx.user["role"] == "customer":
        cats = [r["category_id"] for r in db.all(
            "SELECT p.category_id, COUNT(*) AS n FROM order_items i JOIN orders o ON o.id=i.order_id JOIN products p ON p.id=i.product_id "
            "WHERE o.user_id=? GROUP BY p.category_id ORDER BY n DESC LIMIT 3", (ctx.uid,))]
        cats += [r["category_id"] for r in db.all(
            "SELECT p.category_id FROM wishlist w JOIN products p ON p.id=w.product_id WHERE w.user_id=? LIMIT 3", (ctx.uid,))]
        if cats:
            marks = ",".join("?" for _ in cats)
            rows = db.all(f"{base} AND p.category_id IN ({marks}) AND p.id NOT IN (SELECT i.product_id FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.user_id=? AND i.product_id IS NOT NULL) "
                          f"ORDER BY p.rating_avg DESC, p.units_sold DESC LIMIT 10", params + cats + [ctx.uid])
            imgs = first_images([r["id"] for r in rows])
            rec = [product_card(r, imgs.get(r["id"])) for r in rows]
    if not rec:
        rec = section("p.rating_avg * p.rating_count DESC", 10)
    tree = category_tree(db)
    popular = sorted([c for c in tree if not dept or c["department"] == dept], key=lambda c: -c["count"])
    return {
        "banners": [{k: b[k] for k in ("id", "title", "subtitle", "cta", "link", "theme", "image_url", "video_url", "audio_url")} for b in banners],
        "featured": section("p.featured DESC, p.rating_avg DESC", 10, "AND p.featured=1"),
        "best_sellers": section("p.units_sold DESC", 10),
        "new_arrivals": section("p.created_at DESC", 10),
        "offers": section("(COALESCE(p.mrp,p.selling_price) - p.selling_price) / COALESCE(p.mrp,p.selling_price) DESC", 10, "AND p.mrp > p.selling_price"),
        "recommended": rec,
        "popular_categories": popular[:8],
    }


# ---------------------------------------------------------------- catalogue
SORTS = {
    "popular": "p.units_sold DESC, p.rating_count DESC",
    "price_asc": "p.selling_price ASC",
    "price_desc": "p.selling_price DESC",
    "newest": "p.created_at DESC",
    "rating": "p.rating_avg DESC, p.rating_count DESC",
    "discount": "(COALESCE(p.mrp,p.selling_price) - p.selling_price) / COALESCE(p.mrp,p.selling_price) DESC",
}


@api("GET", "/api/products")
def list_products(ctx):
    db = get_db()
    where, params = [f"p.status IN {VISIBLE}"], []
    q = ctx.q("q")
    if q:
        q = q[:80]
        like = f"%{q.lower()}%"
        where.append("(LOWER(p.name) LIKE ? OR LOWER(p.brand) LIKE ? OR LOWER(c.name) LIKE ? OR LOWER(sc.name) LIKE ? OR LOWER(p.description) LIKE ?)")
        params += [like] * 5
    cat = ctx.q("category")
    if cat:
        row = db.one("SELECT id, parent_id FROM categories WHERE slug=?", (cat,))
        if row:
            where.append("(p.category_id=? OR p.subcategory_id=?)")
            params += [row["id"], row["id"]]
    dept = ctx.q("dept")
    if dept:
        where.append("c.department=?")
        params.append(dept)
    brands = [b for b in (ctx.q("brand") or "").split(",") if b]
    if brands:
        where.append(f"p.brand IN ({','.join('?' for _ in brands)})")
        params += brands
    lo, hi = ctx.q("min"), ctx.q("max")
    if lo:
        where.append("p.selling_price >= ?"); params.append(num(lo, "Min price", lo=0))
    if hi:
        where.append("p.selling_price <= ?"); params.append(num(hi, "Max price", lo=0))
    if ctx.q("rating"):
        where.append("p.rating_avg >= ?"); params.append(num(ctx.q("rating"), "Rating", 0, 5))
    if ctx.q("in_stock") == "1":
        where.append("p.status='active' AND (p.physical_stock - p.reserved_qty - p.unavailable_qty) > 0")
    if ctx.q("offers") == "1":
        where.append("p.mrp > p.selling_price")
    joins = "FROM products p LEFT JOIN categories c ON c.id=p.category_id LEFT JOIN categories sc ON sc.id=p.subcategory_id"
    w = " AND ".join(where)
    total = db.val(f"SELECT COUNT(*) {joins} WHERE {w}", params)
    page, per, off = page_args(ctx, 24, 60)
    order = SORTS.get(ctx.q("sort"), SORTS["popular"])
    rows = db.all(f"SELECT p.* {joins} WHERE {w} ORDER BY {order}, p.id LIMIT {per} OFFSET {off}", params)
    imgs = first_images([r["id"] for r in rows])
    # facets (computed without the brand/price filters so users can widen)
    fw, fp = [f"p.status IN {VISIBLE}"], []
    if cat and row:
        fw.append("(p.category_id=? OR p.subcategory_id=?)"); fp += [row["id"], row["id"]]
    if dept:
        fw.append("c.department=?"); fp.append(dept)
    if q:
        fw.append("(LOWER(p.name) LIKE ? OR LOWER(p.brand) LIKE ? OR LOWER(c.name) LIKE ? OR LOWER(sc.name) LIKE ? OR LOWER(p.description) LIKE ?)")
        fp += [f"%{q.lower()}%"] * 5
    fws = " AND ".join(fw)
    facet_brands = db.all(f"SELECT p.brand AS name, COUNT(*) AS n {joins} WHERE {fws} AND p.brand IS NOT NULL GROUP BY p.brand ORDER BY n DESC, p.brand", fp)
    pr = db.one(f"SELECT MIN(p.selling_price) AS lo, MAX(p.selling_price) AS hi {joins} WHERE {fws}", fp)
    subcats = []
    if cat and row and not row["parent_id"]:
        subcats = db.all("SELECT id, name, slug FROM categories WHERE parent_id=? AND active=1 ORDER BY sort, name", (row["id"],))
    if q and page == 1:
        log_search(q, total, str(local_today()))
    return {"items": [product_card(r, imgs.get(r["id"])) for r in rows], "total": total, "page": page, "per": per,
            "facets": {"brands": facet_brands, "price": {"min": money(pr["lo"] or 0), "max": money(pr["hi"] or 0)},
                       "subcategories": subcats}}


@api("GET", "/api/products/{slug}")
def product_detail(ctx):
    db = get_db()
    p = db.one(f"SELECT * FROM products WHERE slug=? AND status IN {VISIBLE}", (ctx.params["slug"],))
    if not p:
        raise ApiError(404, "Product not found or no longer available.")
    imgs = [r["url"] for r in db.all("SELECT url FROM product_images WHERE product_id=? ORDER BY sort, id", (p["id"],))]
    cat = db.one("SELECT id, name, slug FROM categories WHERE id=?", (p["category_id"],)) if p["category_id"] else None
    sub = db.one("SELECT id, name, slug FROM categories WHERE id=?", (p["subcategory_id"],)) if p["subcategory_id"] else None
    reviews = db.all("SELECT r.rating, r.title, r.body, r.created_at, u.name FROM reviews r JOIN users u ON u.id=r.user_id "
                     "WHERE r.product_id=? AND r.status='published' ORDER BY r.created_at DESC LIMIT 20", (p["id"],))
    for r in reviews:  # show first name + initial only
        parts = (r["name"] or "Customer").split()
        r["name"] = parts[0] + (f" {parts[1][0]}." if len(parts) > 1 else "")
    dist = {i: 0 for i in range(1, 6)}
    for r in db.all("SELECT rating, COUNT(*) AS n FROM reviews WHERE product_id=? AND status='published' GROUP BY rating", (p["id"],)):
        dist[r["rating"]] = r["n"]
    related = db.all(f"SELECT * FROM products WHERE category_id=? AND id<>? AND status IN {VISIBLE} ORDER BY units_sold DESC LIMIT 8",
                     (p["category_id"], p["id"]))
    rimgs = first_images([r["id"] for r in related])
    can_review, in_wishlist, in_cart = False, False, 0
    if ctx.user and ctx.user["role"] == "customer":
        can_review = bool(db.one("SELECT o.id FROM orders o JOIN order_items i ON i.order_id=o.id WHERE o.user_id=? AND i.product_id=? "
                                 "AND o.status IN ('delivered','return_requested','return_in_progress','returned','refund_processing','refunded')",
                                 (ctx.uid, p["id"]))) and not db.one("SELECT id FROM reviews WHERE user_id=? AND product_id=?", (ctx.uid, p["id"]))
        in_wishlist = bool(db.one("SELECT id FROM wishlist WHERE user_id=? AND product_id=?", (ctx.uid, p["id"])))
        in_cart = db.val("SELECT qty FROM cart_items WHERE user_id=? AND product_id=?", (ctx.uid, p["id"])) or 0
    s = get_settings()
    a = available(p) if p["status"] == "active" else 0
    return {
        "id": p["id"], "name": p["name"], "slug": p["slug"], "description": p["description"], "brand": p["brand"],
        "sku": p["sku"], "price": money(p["selling_price"]), "mrp": money(p["mrp"]) if p["mrp"] else None,
        "discount": discount_pct(p), "tax_rate": p["tax_rate"], "rating": round(p["rating_avg"] or 0, 1),
        "reviews_count": p["rating_count"], "rating_distribution": dist, "stock": stock_label(p),
        "available": a, "max_qty": max(0, min(a, p["max_per_order"] or 10, s["max_qty_per_order"])),
        "specs": jload(p["specs"], {}), "weight_g": p["weight_g"], "dimensions": p["dimensions"],
        "shipping_req": p["shipping_req"], "images": imgs or ["/static/common/placeholder.svg"],
        "category": cat, "subcategory": sub, "sample": bool(p["is_sample"]), "reviews": reviews,
        "related": [product_card(r, rimgs.get(r["id"])) for r in related],
        "can_review": can_review, "in_wishlist": in_wishlist, "in_cart": in_cart,
        "return_window_days": s["return_window_days"],
        "sold_by": (db.one("SELECT v.business_name AS n FROM product_vendors pv JOIN vendors v ON v.id=pv.vendor_id WHERE pv.product_id=?", (p["id"],)) or {}).get("n")
                   or s.get("store_name") or "PVC Paltan Store",
    }


@api("POST", "/api/track", limit="track")
def track(ctx):
    pid = ctx.get("product_id")
    if ctx.get("type") == "view" and isinstance(pid, int):
        db = get_db()
        if db.one("SELECT id FROM products WHERE id=?", (pid,)):
            bump_activity(pid, "views", str(local_today()))
    return {"ok": True}


# ---------------------------------------------------------------- cart
def cart_payload(db, uid):
    rows = db.all("SELECT c.qty, p.* FROM cart_items c JOIN products p ON p.id=c.product_id WHERE c.user_id=? ORDER BY c.id", (uid,))
    imgs = first_images([r["id"] for r in rows])
    items = []
    for r in rows:
        card = product_card(r, imgs.get(r["id"]))
        a = available(r) if r["status"] == "active" else 0
        card.update({"qty": r["qty"], "available_qty": a, "line_total": money(r["selling_price"] * r["qty"]),
                     "line_mrp": money((r["mrp"] or r["selling_price"]) * r["qty"]),
                     "issue": None if r["status"] == "active" and r["qty"] <= a else
                     ("Out of stock" if a <= 0 else f"Only {a} available")})
        items.append(card)
    quote = osvc.build_quote(uid)
    return {"items": items, "quote": quote}


@api("GET", "/api/cart", auth="customer")
def get_cart(ctx):
    return cart_payload(get_db(), ctx.uid)


@api("POST", "/api/cart", auth="customer")
def set_cart(ctx):
    db = get_db()
    pid = int(num(ctx.get("product_id"), "Product", integer=True))
    qty = int(num(ctx.get("qty", 1), "Quantity", lo=0, hi=99, integer=True))
    mode = ctx.get("mode", "set")
    p = db.one("SELECT * FROM products WHERE id=?", (pid,))
    if not p or p["status"] not in ("active", "out_of_stock"):
        raise ApiError(404, "Product not available.")
    s = get_settings()
    cur = db.val("SELECT qty FROM cart_items WHERE user_id=? AND product_id=?", (ctx.uid, pid)) or 0
    new = cur + qty if mode == "add" else qty
    if new <= 0:
        db.run("DELETE FROM cart_items WHERE user_id=? AND product_id=?", (ctx.uid, pid))
        return cart_payload(db, ctx.uid)
    a = available(p) if p["status"] == "active" else 0
    max_q = min(p["max_per_order"] or 10, s["max_qty_per_order"])
    if a <= 0:
        raise ApiError(409, f"{p['name']} is out of stock.")
    if new > a:
        raise ApiError(409, f"Only {a} unit(s) of {p['name']} available.")
    if new > max_q:
        raise ApiError(409, f"You can buy at most {max_q} units of this item per order.")
    if cur:
        db.run("UPDATE cart_items SET qty=? WHERE user_id=? AND product_id=?", (new, ctx.uid, pid))
    else:
        db.insert("cart_items", {"user_id": ctx.uid, "product_id": pid, "qty": new, "added_at": now_iso()})
    if new > cur:
        bump_activity(pid, "add_to_cart", str(local_today()))
    return cart_payload(db, ctx.uid)


@api("DELETE", "/api/cart/{pid:int}", auth="customer")
def remove_cart(ctx):
    db = get_db()
    db.run("DELETE FROM cart_items WHERE user_id=? AND product_id=?", (ctx.uid, ctx.params["pid"]))
    return cart_payload(db, ctx.uid)


# ---------------------------------------------------------------- wishlist
@api("GET", "/api/wishlist", auth="customer")
def get_wishlist(ctx):
    db = get_db()
    rows = db.all("SELECT p.* FROM wishlist w JOIN products p ON p.id=w.product_id WHERE w.user_id=? AND p.status IN ('active','out_of_stock') "
                  "ORDER BY w.id DESC", (ctx.uid,))
    imgs = first_images([r["id"] for r in rows])
    return {"items": [product_card(r, imgs.get(r["id"])) for r in rows]}


@api("POST", "/api/wishlist", auth="customer")
def toggle_wishlist(ctx):
    db = get_db()
    pid = int(num(ctx.get("product_id"), "Product", integer=True))
    if not db.one("SELECT id FROM products WHERE id=?", (pid,)):
        raise ApiError(404, "Product not found.")
    if db.one("SELECT id FROM wishlist WHERE user_id=? AND product_id=?", (ctx.uid, pid)):
        db.run("DELETE FROM wishlist WHERE user_id=? AND product_id=?", (ctx.uid, pid))
        added = False
    else:
        db.insert("wishlist", {"user_id": ctx.uid, "product_id": pid, "added_at": now_iso()})
        bump_activity(pid, "wishlist", str(local_today()))
        added = True
    return {"added": added, "count": db.val("SELECT COUNT(*) FROM wishlist WHERE user_id=?", (ctx.uid,))}


# ---------------------------------------------------------------- account & addresses
@api("PUT", "/api/account/profile", auth="user")
def update_profile(ctx):
    db = get_db()
    name = text(ctx.get("name"), "Name", max_len=80, min_len=2)
    phone = text(ctx.get("phone"), "Phone", required=False, max_len=16)
    db.run("UPDATE users SET name=?, phone=? WHERE id=?", (name, phone, ctx.uid))
    return {"ok": True}


def _addr_fields(ctx):
    import re
    d = {
        "label": text(ctx.get("label"), "Label", required=False, max_len=30),
        "name": text(ctx.get("name"), "Recipient name", max_len=80),
        "phone": text(ctx.get("phone"), "Phone", max_len=16),
        "line1": text(ctx.get("line1"), "Address line 1", max_len=160),
        "line2": text(ctx.get("line2"), "Address line 2", required=False, max_len=160),
        "city": text(ctx.get("city"), "City", max_len=60),
        "state": text(ctx.get("state"), "State", max_len=60),
        "pincode": text(ctx.get("pincode"), "PIN code", max_len=6),
    }
    if not re.fullmatch(r"\d{6}", d["pincode"]):
        raise ApiError(400, "PIN code must be 6 digits.")
    if not re.fullmatch(r"[0-9+\- ]{8,16}", d["phone"]):
        raise ApiError(400, "Enter a valid phone number.")
    return d


@api("GET", "/api/account/addresses", auth="customer")
def list_addresses(ctx):
    return {"items": get_db().all("SELECT * FROM addresses WHERE user_id=? ORDER BY is_default DESC, id DESC", (ctx.uid,))}


@api("POST", "/api/account/addresses", auth="customer")
def add_address(ctx):
    db = get_db()
    d = _addr_fields(ctx)
    if db.val("SELECT COUNT(*) FROM addresses WHERE user_id=?", (ctx.uid,)) >= 10:
        raise ApiError(400, "You can save up to 10 addresses.")
    first = not db.one("SELECT id FROM addresses WHERE user_id=?", (ctx.uid,))
    if ctx.get("is_default") or first:
        db.run("UPDATE addresses SET is_default=0 WHERE user_id=?", (ctx.uid,))
    aid = db.insert("addresses", {**d, "user_id": ctx.uid, "is_default": 1 if (ctx.get("is_default") or first) else 0,
                                  "created_at": now_iso()})
    return db.one("SELECT * FROM addresses WHERE id=?", (aid,))


@api("PUT", "/api/account/addresses/{aid:int}", auth="customer")
def edit_address(ctx):
    db = get_db()
    if not db.one("SELECT id FROM addresses WHERE id=? AND user_id=?", (ctx.params["aid"], ctx.uid)):
        raise ApiError(404, "Address not found.")
    d = _addr_fields(ctx)
    if ctx.get("is_default"):
        db.run("UPDATE addresses SET is_default=0 WHERE user_id=?", (ctx.uid,))
        d["is_default"] = 1
    db.update("addresses", ctx.params["aid"], d)
    return db.one("SELECT * FROM addresses WHERE id=?", (ctx.params["aid"],))


@api("DELETE", "/api/account/addresses/{aid:int}", auth="customer")
def delete_address(ctx):
    db = get_db()
    db.run("DELETE FROM addresses WHERE id=? AND user_id=?", (ctx.params["aid"], ctx.uid))
    return {"ok": True}


# ---------------------------------------------------------------- checkout & orders
@api("POST", "/api/checkout/quote", auth="customer")
def checkout_quote(ctx):
    return osvc.build_quote(ctx.uid, ctx.get("delivery_method"), ctx.get("coupon"), ctx.get("payment_method"))


@api("POST", "/api/orders", auth="customer", limit="order")
def create_order(ctx):
    aid = int(num(ctx.get("address_id"), "Delivery address", integer=True))
    pm = ctx.get("payment_method")
    if pm not in ("cod", "razorpay", "sandbox", "upi"):
        raise ApiError(400, "Choose a payment method.")
    order = osvc.place_order(ctx.user, aid, ctx.get("delivery_method"), pm, (ctx.get("coupon") or "").strip() or None,
                             ctx.get("expected_total"))
    out = {"order_no": order["order_no"], "status": order["status"], "grand_total": order["grand_total"]}
    if pm in osvc.ONLINE_METHODS:
        out["payment"] = psvc.start_payment(order, ctx.user, pm)
    return out


def _own_order(ctx):
    db = get_db()
    o = db.one("SELECT * FROM orders WHERE order_no=? AND user_id=?", (ctx.params["no"], ctx.uid))
    if not o:  # same response whether it doesn't exist or belongs to someone else
        raise ApiError(404, "Order not found.")
    return o


@api("GET", "/api/orders", auth="customer")
def my_orders(ctx):
    db = get_db()
    osvc.expire_stale_payments()
    rows = db.all("SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 100", (ctx.uid,))
    out = []
    for o in rows:
        items = db.all("SELECT product_id, name, qty FROM order_items WHERE order_id=?", (o["id"],))
        imgs = first_images([i["product_id"] for i in items if i["product_id"]])
        out.append({"order_no": o["order_no"], "status": o["status"], "status_label": osvc.STATUS_LABEL[o["status"]],
                    "grand_total": o["grand_total"], "created_at": o["created_at"], "payment_method": o["payment_method"],
                    "payment_status": o["payment_status"], "est_delivery_to": o["est_delivery_to"],
                    "items": [{"name": i["name"], "qty": i["qty"], "image": imgs.get(i["product_id"], "/static/common/placeholder.svg")} for i in items]})
    return {"items": out}


@api("GET", "/api/orders/{no}", auth="customer")
def my_order(ctx):
    osvc.expire_stale_payments()
    return osvc.serialize_order(get_db(), _own_order(ctx))


@api("POST", "/api/orders/{no}/cancel", auth="customer")
def cancel_order(ctx):
    reason = text(ctx.get("reason"), "Reason", max_len=300)
    osvc.customer_cancel(_own_order(ctx), ctx.user, reason)
    return osvc.serialize_order(get_db(), _own_order(ctx))


@api("POST", "/api/orders/{no}/return", auth="customer")
def return_order(ctx):
    reason = text(ctx.get("reason"), "Reason", max_len=300)
    osvc.customer_return(_own_order(ctx), ctx.user, reason)
    return osvc.serialize_order(get_db(), _own_order(ctx))


@api("POST", "/api/orders/{no}/pay", auth="customer", limit="pay")
def pay_order(ctx):
    osvc.expire_stale_payments()
    return psvc.start_payment(_own_order(ctx), ctx.user, ctx.get("method"))


@api("POST", "/api/payments/razorpay/verify", auth="customer", limit="pay")
def rzp_verify(ctx):
    o, p, s = ctx.require("razorpay_order_id", "razorpay_payment_id", "razorpay_signature")
    order = psvc.verify_razorpay(ctx.user, o, p, s)
    return {"ok": True, "order_no": order["order_no"]}


@api("POST", "/api/orders/{no}/upi-submit", auth="customer", limit="pay")
def upi_submit(ctx):
    order = psvc.submit_upi(_own_order(ctx), ctx.user, ctx.get("utr"))
    return osvc.serialize_order(get_db(), order)


@api("POST", "/api/payments/sandbox/complete", auth="customer", limit="pay")
def sandbox_complete(ctx):
    pid = int(num(ctx.get("payment_id"), "Payment", integer=True))
    return psvc.complete_sandbox(ctx.user, pid, ctx.get("token"), ctx.get("outcome"))


# ---------------------------------------------------------------- reviews & notifications
@api("POST", "/api/reviews", auth="customer", limit="review")
def add_review(ctx):
    db = get_db()
    pid = int(num(ctx.get("product_id"), "Product", integer=True))
    rating = int(num(ctx.get("rating"), "Rating", 1, 5, integer=True))
    title = text(ctx.get("title"), "Title", required=False, max_len=100)
    body = text(ctx.get("body"), "Review", required=False, max_len=2000)
    order = db.one("SELECT o.id FROM orders o JOIN order_items i ON i.order_id=o.id WHERE o.user_id=? AND i.product_id=? AND "
                   "o.status IN ('delivered','return_requested','return_in_progress','returned','refund_processing','refunded') LIMIT 1",
                   (ctx.uid, pid))
    if not order:
        raise ApiError(403, "You can review products after they are delivered to you.")
    if db.one("SELECT id FROM reviews WHERE user_id=? AND product_id=?", (ctx.uid, pid)):
        raise ApiError(409, "You have already reviewed this product.")
    with transaction(db):
        db.insert("reviews", {"product_id": pid, "user_id": ctx.uid, "order_id": order["id"], "rating": rating, "title": title,
                              "body": body, "status": "published", "created_at": now_iso()})
        recalc_rating(db, pid)
    return {"ok": True}


def recalc_rating(db, pid):
    r = db.one("SELECT COUNT(*) AS n, AVG(rating) AS a FROM reviews WHERE product_id=? AND status='published'", (pid,))
    db.run("UPDATE products SET rating_avg=?, rating_count=? WHERE id=?", (round(r["a"] or 0, 2), r["n"], pid))


@api("GET", "/api/notifications", auth="user")
def notifications(ctx):
    return {"items": get_db().all("SELECT id, title, body, link, is_read, created_at FROM notifications WHERE user_id=? "
                                  "ORDER BY id DESC LIMIT 50", (ctx.uid,))}


@api("POST", "/api/notifications/read", auth="user")
def notifications_read(ctx):
    get_db().run("UPDATE notifications SET is_read=1 WHERE user_id=?", (ctx.uid,))
    return {"ok": True}
