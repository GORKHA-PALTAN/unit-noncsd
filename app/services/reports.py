"""Dashboard KPIs, finance and grouped reports — all computed from stored records."""
import csv
import io
from collections import defaultdict
from datetime import date, timedelta

from ..db import get_db, local_date, local_day_start_utc, local_today
from ..web import ApiError
from .common import available, money
from .orders import SALE_EXCLUDED, STATUS_LABEL

EXCL = ",".join(f"'{s}'" for s in SALE_EXCLUDED)


def resolve_range(rng, d_from=None, d_to=None):
    today = local_today()
    if rng == "today":
        return today, today
    if rng == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if rng == "7d":
        return today - timedelta(days=6), today
    if rng == "month":
        return today.replace(day=1), today
    if rng == "prev_month":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    if rng == "custom":
        try:
            a, b = date.fromisoformat(d_from), date.fromisoformat(d_to)
        except (TypeError, ValueError):
            raise ApiError(400, "Choose a valid custom date range.")
        if b < a:
            a, b = b, a
        if (b - a).days > 1100:
            raise ApiError(400, "Custom range is limited to 3 years.")
        return a, b
    return today - timedelta(days=29), today  # 30d default


def _bounds(a, b):
    return local_day_start_utc(a), local_day_start_utc(b + timedelta(days=1))


def overview(rng="30d", d_from=None, d_to=None):
    db = get_db()
    a, b = resolve_range(rng, d_from, d_to)
    start, end = _bounds(a, b)
    today = local_today()
    t_start, t_end = _bounds(today, today)
    m_start = local_day_start_utc(today.replace(day=1))

    prods = db.all("SELECT * FROM products")
    for p in prods:
        p["available"] = available(p)
    low = sorted([p for p in prods if p["status"] == "active" and 0 < p["available"] <= (p["low_stock_threshold"] or 0)],
                 key=lambda p: p["available"])
    out = sorted([p for p in prods if p["status"] in ("active", "out_of_stock") and p["available"] <= 0], key=lambda p: p["name"])
    status_counts = defaultdict(int)
    for p in prods:
        status_counts[p["status"]] += 1

    def sales_between(s, e):
        r = db.one(f"SELECT COUNT(*) AS n, COALESCE(SUM(grand_total),0) AS gross, COALESCE(SUM(subtotal - coupon_discount - tax_total + delivery_charge),0) AS net, "
                   f"COALESCE(SUM(cost_total),0) AS cogs FROM orders WHERE created_at >= ? AND created_at < ? AND status NOT IN ({EXCL})", (s, e))
        return r

    rng_sales = sales_between(start, end)
    today_sales = sales_between(t_start, t_end)
    month_sales = sales_between(m_start, t_end)
    all_sales = db.one(f"SELECT COUNT(*) AS n, COALESCE(SUM(grand_total),0) AS gross FROM orders WHERE status NOT IN ({EXCL})")

    st = {r["status"]: r["n"] for r in db.all("SELECT status, COUNT(*) AS n FROM orders WHERE created_at >= ? AND created_at < ? GROUP BY status", (start, end))}
    st_all = {r["status"]: r["n"] for r in db.all("SELECT status, COUNT(*) AS n FROM orders GROUP BY status")}
    expenses = db.one("SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS total FROM expenses WHERE date >= ? AND date <= ?", (str(a), str(b)))
    gross_profit = money(rng_sales["net"] - rng_sales["cogs"])

    # daily series
    days = (b - a).days + 1
    series = {str(a + timedelta(days=i)): {"revenue": 0.0, "orders": 0} for i in range(days)}
    for r in db.all(f"SELECT created_at, grand_total FROM orders WHERE created_at >= ? AND created_at < ? AND status NOT IN ({EXCL})", (start, end)):
        k = str(local_date(r["created_at"]))
        if k in series:
            series[k]["revenue"] += r["grand_total"]
            series[k]["orders"] += 1
    by_cat = db.all(
        f"SELECT COALESCE(pc.name, c.name, 'Uncategorised') AS name, SUM(i.line_total) AS revenue, SUM(i.qty) AS units "
        f"FROM order_items i JOIN orders o ON o.id=i.order_id LEFT JOIN products p ON p.id=i.product_id "
        f"LEFT JOIN categories c ON c.id=p.category_id LEFT JOIN categories pc ON pc.id=c.parent_id "
        f"WHERE o.created_at >= ? AND o.created_at < ? AND o.status NOT IN ({EXCL}) GROUP BY 1 ORDER BY 2 DESC", (start, end))
    top = db.all(
        f"SELECT i.product_id, i.name, SUM(i.qty) AS units, SUM(i.line_total) AS revenue FROM order_items i JOIN orders o ON o.id=i.order_id "
        f"WHERE o.created_at >= ? AND o.created_at < ? AND o.status NOT IN ({EXCL}) GROUP BY i.product_id, i.name ORDER BY revenue DESC LIMIT 8",
        (start, end))
    pay_split = db.all(f"SELECT payment_method AS method, COUNT(*) AS n, SUM(grand_total) AS amount FROM orders "
                       f"WHERE created_at >= ? AND created_at < ? AND status NOT IN ({EXCL}) GROUP BY payment_method", (start, end))
    recent = db.all("SELECT o.id, o.order_no, o.status, o.grand_total, o.payment_method, o.payment_status, o.created_at, "
                    "o.buyer_code, u.name AS customer FROM orders o JOIN users u ON u.id=o.user_id ORDER BY o.created_at DESC LIMIT 8")
    for r in recent:
        r["status_label"] = STATUS_LABEL.get(r["status"], r["status"])

    cust_total = db.val("SELECT COUNT(*) FROM users WHERE role='customer'")
    cust_new = db.val("SELECT COUNT(*) FROM users WHERE role='customer' AND created_at >= ? AND created_at < ?", (start, end))
    cod_due = db.one("SELECT COUNT(*) AS n, COALESCE(SUM(grand_total),0) AS amt FROM orders WHERE payment_method='cod' AND payment_status='pending' AND status='delivered'")

    def g(d, *keys):
        return sum(d.get(k, 0) for k in keys)

    return {
        "range": {"from": str(a), "to": str(b), "key": rng},
        "products": {"total": len(prods), "active": status_counts["active"], "inactive": status_counts["inactive"],
                     "draft": status_counts["draft"], "out_of_stock_status": status_counts["out_of_stock"],
                     "total_stock": sum(p["physical_stock"] for p in prods),
                     "available_stock": sum(p["available"] for p in prods),
                     "reserved_stock": sum(p["reserved_qty"] for p in prods),
                     "valuation_cost": money(sum(p["physical_stock"] * (p["cost_price"] or 0) for p in prods)),
                     "valuation_retail": money(sum(p["physical_stock"] * (p["selling_price"] or 0) for p in prods)),
                     "low_stock": len(low), "out_of_stock": len(out)},
        "orders": {"total_all_time": sum(st_all.values()), "in_range": sum(st.values()),
                   "today": db.val("SELECT COUNT(*) FROM orders WHERE created_at >= ? AND created_at < ?", (t_start, t_end)),
                   "awaiting_processing": g(st_all, "placed", "payment_confirmed", "confirmed", "processing", "packed"),
                   "dispatched": g(st, "dispatched", "in_transit", "out_for_delivery"),
                   "delivered": g(st, "delivered"), "cancelled": g(st, "cancelled"),
                   "awaiting_payment": g(st_all, "payment_pending"),
                   "returns_open": g(st_all, "return_requested", "return_in_progress", "cancel_requested"),
                   "cod_to_collect": cod_due["n"], "cod_to_collect_amount": money(cod_due["amt"]),
                   "by_status": [{"status": k, "label": STATUS_LABEL.get(k, k), "n": v} for k, v in sorted(st.items(), key=lambda x: -x[1])]},
        "customers": {"total": cust_total, "new": cust_new},
        "sales": {"total_all_time": money(all_sales["gross"]), "in_range": money(rng_sales["gross"]),
                  "orders_in_range": rng_sales["n"], "today": money(today_sales["gross"]), "month": money(month_sales["gross"]),
                  "avg_order_value": money(rng_sales["gross"] / rng_sales["n"]) if rng_sales["n"] else 0,
                  "net_revenue_ex_tax": money(rng_sales["net"]), "cogs": money(rng_sales["cogs"]),
                  "gross_profit": gross_profit,
                  "gross_margin_pct": round(gross_profit / rng_sales["net"] * 100, 1) if rng_sales["net"] else None,
                  "expenses": money(expenses["total"]), "expense_entries": expenses["n"],
                  "net_profit": money(gross_profit - expenses["total"]) if expenses["n"] else None},
        "series": [{"day": k, **{kk: money(vv) if kk == "revenue" else vv for kk, vv in v.items()}} for k, v in series.items()],
        "by_category": [{"name": r["name"], "revenue": money(r["revenue"]), "units": r["units"]} for r in by_cat],
        "top_products": [{"product_id": r["product_id"], "name": r["name"], "units": r["units"], "revenue": money(r["revenue"])} for r in top],
        "payment_split": [{"method": r["method"], "n": r["n"], "amount": money(r["amount"])} for r in pay_split],
        "low_stock_items": [{"id": p["id"], "name": p["name"], "sku": p["sku"], "available": p["available"],
                             "threshold": p["low_stock_threshold"]} for p in low[:10]],
        "out_of_stock_items": [{"id": p["id"], "name": p["name"], "sku": p["sku"]} for p in out[:10]],
        "recent_orders": recent,
    }


def grouped_report(group, rng, d_from=None, d_to=None):
    db = get_db()
    a, b = resolve_range(rng, d_from, d_to)
    start, end = _bounds(a, b)
    if group == "company":
        key_sql, label_join = "COALESCE(o.buyer_company,'—')", "LEFT JOIN companies c ON c.code=o.buyer_company"
        name_sql = "COALESCE(c.name, 'No buyer code')"
    elif group == "rank":
        key_sql, label_join = "COALESCE(o.buyer_category,'—')", "LEFT JOIN rank_categories c ON c.code=o.buyer_category"
        name_sql = "COALESCE(c.name, 'No buyer code')"
    elif group == "buyer":
        key_sql, label_join, name_sql = "COALESCE(o.buyer_code,'—')", "", "COALESCE(o.buyer_code,'No buyer code')"
    elif group == "payment":
        key_sql, label_join, name_sql = "o.payment_method", "", "o.payment_method"
    elif group == "day":
        key_sql, label_join, name_sql = "SUBSTR(o.created_at,1,10)", "", "SUBSTR(o.created_at,1,10)"
    else:
        raise ApiError(400, "Unknown report grouping.")
    rows = db.all(
        f"SELECT {key_sql} AS k, {name_sql} AS name, COUNT(*) AS orders, SUM(o.grand_total) AS sales, "
        f"SUM(o.cost_total) AS cogs, SUM(CASE WHEN o.payment_status='paid' THEN o.grand_total ELSE 0 END) AS paid, "
        f"SUM(CASE WHEN o.payment_method='cod' AND o.payment_status='pending' THEN o.grand_total ELSE 0 END) AS cod_pending "
        f"FROM orders o {label_join} WHERE o.created_at >= ? AND o.created_at < ? AND o.status NOT IN ({EXCL}) "
        f"GROUP BY 1, 2 ORDER BY sales DESC", (start, end))
    if group == "day":  # re-bucket by local day
        buckets = defaultdict(lambda: {"orders": 0, "sales": 0.0, "cogs": 0.0, "paid": 0.0, "cod_pending": 0.0})
        for o in db.all(f"SELECT created_at, grand_total, cost_total, payment_status, payment_method FROM orders "
                        f"WHERE created_at >= ? AND created_at < ? AND status NOT IN ({EXCL})", (start, end)):
            k = str(local_date(o["created_at"]))
            bk = buckets[k]
            bk["orders"] += 1; bk["sales"] += o["grand_total"]; bk["cogs"] += o["cost_total"] or 0
            if o["payment_status"] == "paid":
                bk["paid"] += o["grand_total"]
            elif o["payment_method"] == "cod":
                bk["cod_pending"] += o["grand_total"]
        rows = [{"k": k, "name": k, **v} for k, v in sorted(buckets.items())]
    for r in rows:
        for f in ("sales", "cogs", "paid", "cod_pending"):
            r[f] = money(r[f])
    return {"range": {"from": str(a), "to": str(b)}, "group": group, "rows": rows,
            "totals": {"orders": sum(r["orders"] for r in rows), "sales": money(sum(r["sales"] for r in rows)),
                       "paid": money(sum(r["paid"] for r in rows)), "cod_pending": money(sum(r["cod_pending"] for r in rows))}}


# ------------------------------------------------------------------ CSV export
def _safe(v):
    """Neutralise spreadsheet formula injection."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def to_csv(headers, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow([_safe(r.get(h)) for h in headers])
    return "﻿" + buf.getvalue()


def export(kind, rng, d_from=None, d_to=None):
    db = get_db()
    a, b = resolve_range(rng, d_from, d_to)
    start, end = _bounds(a, b)
    if kind == "products":
        rows = db.all("SELECT p.id, p.sku, p.name, p.brand, c.name AS category, sc.name AS subcategory, p.status, p.cost_price, "
                      "p.selling_price, p.mrp, p.tax_rate, p.physical_stock, p.reserved_qty, p.unavailable_qty, p.units_sold, "
                      "p.rating_avg, p.rating_count, p.weight_g, p.dimensions, p.is_sample, p.created_at, p.updated_at "
                      "FROM products p LEFT JOIN categories c ON c.id=p.category_id LEFT JOIN categories sc ON sc.id=p.subcategory_id ORDER BY p.id")
        for r in rows:
            r["available"] = r["physical_stock"] - r["reserved_qty"] - r["unavailable_qty"]
        heads = ["id", "sku", "name", "brand", "category", "subcategory", "status", "cost_price", "selling_price", "mrp", "tax_rate",
                 "physical_stock", "reserved_qty", "unavailable_qty", "available", "units_sold", "rating_avg", "rating_count",
                 "weight_g", "dimensions", "is_sample", "created_at", "updated_at"]
    elif kind == "inventory":
        rows = db.all("SELECT m.created_at, p.sku, p.name, m.type, m.qty, m.physical_after, m.reserved_after, m.unavailable_after, "
                      "o.order_no, m.note, u.name AS by_user FROM inventory_movements m JOIN products p ON p.id=m.product_id "
                      "LEFT JOIN orders o ON o.id=m.order_id LEFT JOIN users u ON u.id=m.actor_id "
                      "WHERE m.created_at >= ? AND m.created_at < ? ORDER BY m.created_at", (start, end))
        heads = ["created_at", "sku", "name", "type", "qty", "physical_after", "reserved_after", "unavailable_after", "order_no", "note", "by_user"]
    elif kind == "orders":
        rows = db.all("SELECT o.order_no, o.created_at, u.name AS customer, u.email, o.buyer_code, o.status, o.payment_method, "
                      "o.payment_status, o.subtotal, o.coupon_discount, o.delivery_charge, o.tax_total, o.grand_total, o.cost_total, "
                      "o.ship_name, o.ship_phone, o.courier, o.tracking_no, o.is_sample FROM orders o JOIN users u ON u.id=o.user_id "
                      "WHERE o.created_at >= ? AND o.created_at < ? ORDER BY o.created_at", (start, end))
        heads = ["order_no", "created_at", "customer", "email", "buyer_code", "status", "payment_method", "payment_status", "subtotal",
                 "coupon_discount", "delivery_charge", "tax_total", "grand_total", "cost_total", "ship_name", "ship_phone",
                 "courier", "tracking_no", "is_sample"]
    elif kind == "order_items":
        rows = db.all("SELECT o.order_no, o.created_at, o.status, i.sku, i.name, i.qty, i.unit_price, i.mrp, i.cost_price, i.tax_rate, i.line_total "
                      "FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.created_at >= ? AND o.created_at < ? ORDER BY o.created_at", (start, end))
        heads = ["order_no", "created_at", "status", "sku", "name", "qty", "unit_price", "mrp", "cost_price", "tax_rate", "line_total"]
    elif kind == "sales":
        rows = grouped_report("day", rng, d_from, d_to)["rows"]
        for r in rows:
            r["day"] = r["k"]; r["gross_profit_est"] = money(r["sales"] - r["cogs"])
        heads = ["day", "orders", "sales", "cogs", "gross_profit_est", "paid", "cod_pending"]
    elif kind == "customers":
        rows = db.all("SELECT u.id, u.name, u.email, u.phone, u.status, u.created_at, b.code AS buyer_code, "
                      "(SELECT COUNT(*) FROM orders o WHERE o.user_id=u.id) AS orders, "
                      f"(SELECT COALESCE(SUM(grand_total),0) FROM orders o WHERE o.user_id=u.id AND o.status NOT IN ({EXCL})) AS spent "
                      "FROM users u LEFT JOIN buyers b ON b.id=u.buyer_id WHERE u.role='customer' ORDER BY u.id")
        heads = ["id", "name", "email", "phone", "status", "created_at", "buyer_code", "orders", "spent"]
    elif kind == "buyers":
        rows = db.all("SELECT b.code, b.company_code, b.category_code, b.seniority, b.real_name, b.active, u.email AS linked_account "
                      "FROM buyers b LEFT JOIN users u ON u.id=b.user_id ORDER BY b.company_code, b.category_code, b.seniority")
        heads = ["code", "company_code", "category_code", "seniority", "real_name", "active", "linked_account"]
    elif kind in ("company", "rank", "buyer"):
        rows = grouped_report(kind, rng, d_from, d_to)["rows"]
        heads = ["k", "name", "orders", "sales", "paid", "cod_pending", "cogs"]
    else:
        raise ApiError(404, "Unknown export.")
    return to_csv(heads, rows), f"{kind}_{a}_{b}.csv"
