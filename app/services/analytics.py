"""Business intelligence: demand analysis, classifications, recommendations and forecasts.

Everything here is computed from rows stored in the database (orders, order items, stock, product
views, add-to-cart events, searches, returns). Nothing is invented: when there is not enough data
the module says so. Forecasts are statistical estimates (damped Holt trend x weekday seasonality)
and are always labelled separately from recorded history.
"""
import json
import math
import statistics
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import timedelta

from .. import config
from ..db import get_db, local_date, local_day_start_utc, local_today, parse_iso, now_utc
from .common import available, get_settings, money
from .orders import SALE_EXCLUDED

EXCL = ",".join(f"'{s}'" for s in SALE_EXCLUDED)


# ------------------------------------------------------------------ data access
def sales_lines(day_from, day_to=None):
    """Item-level sales rows for valid orders between two local dates (inclusive)."""
    db = get_db()
    day_to = day_to or local_today()
    start = local_day_start_utc(day_from)
    end = local_day_start_utc(day_to + timedelta(days=1))
    rows = db.all(
        f"SELECT o.id AS order_id, o.created_at, o.user_id, i.product_id, i.qty, i.line_total, i.cost_price, "
        f"p.category_id FROM order_items i JOIN orders o ON o.id=i.order_id LEFT JOIN products p ON p.id=i.product_id "
        f"WHERE o.created_at >= ? AND o.created_at < ? AND o.status NOT IN ({EXCL})", (start, end))
    for r in rows:
        r["day"] = local_date(r["created_at"])
    return rows


def first_sale_day():
    db = get_db()
    row = db.one(f"SELECT MIN(created_at) AS m FROM orders WHERE status NOT IN ({EXCL})")
    return local_date(row["m"]) if row and row["m"] else None


def daily_series(lines, day_from, day_to, key=None, value="qty"):
    n = (day_to - day_from).days + 1
    series = [0.0] * n
    for r in lines:
        if key and not key(r):
            continue
        idx = (r["day"] - day_from).days
        if 0 <= idx < n:
            series[idx] += float(r[value] or 0)
    return series


# ------------------------------------------------------------------ forecasting
def _weekday_index(series, start_day):
    """Multiplicative weekday factors from the most recent 8 weeks (falls back to flat)."""
    recent = series[-56:] if len(series) >= 28 else series
    offset = len(series) - len(recent)
    sums, counts = [0.0] * 7, [0] * 7
    for i, v in enumerate(recent):
        wd = (start_day + timedelta(days=offset + i)).weekday()
        sums[wd] += v
        counts[wd] += 1
    means = [sums[i] / counts[i] if counts[i] else 0 for i in range(7)]
    overall = sum(means) / 7 if sum(means) else 0
    if overall <= 0 or len(series) < 21:
        return [1.0] * 7
    idx = [m / overall if m > 0 else 0.5 for m in means]
    # shrink towards 1 to avoid over-fitting noise
    return [0.6 * x + 0.4 for x in idx]


def _holt(y, alpha, beta, phi):
    level, trend = y[0], 0.0
    fitted, sse = [], 0.0
    for t in range(1, len(y)):
        pred = level + phi * trend
        fitted.append(pred)
        err = y[t] - pred
        sse += err * err
        new_level = alpha * y[t] + (1 - alpha) * (level + phi * trend)
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        level = new_level
    return level, trend, fitted, sse


def fit_forecast(series, start_day, horizon):
    """Damped-trend exponential smoothing on de-seasonalised daily values."""
    if len(series) < 14:
        return None
    w = _weekday_index(series, start_day)
    des = [v / w[(start_day + timedelta(days=i)).weekday()] for i, v in enumerate(series)]
    best = None
    for a in (0.05, 0.1, 0.2, 0.3, 0.5):
        for b in (0.0, 0.02, 0.05, 0.1):
            for phi in (0.9, 0.95):
                lv, tr, fitted, sse = _holt(des, a, b, phi)
                if best is None or sse < best[0]:
                    best = (sse, a, b, phi, lv, tr, fitted)
    sse, a, b, phi, level, trend, fitted = best
    resid = [des[i + 1] - f for i, f in enumerate(fitted)]
    sd = statistics.pstdev(resid[-60:]) if len(resid) > 2 else 0
    out = []
    last_day = start_day + timedelta(days=len(series) - 1)
    damp = 0.0
    for h in range(1, horizon + 1):
        damp += phi ** h
        base = max(0.0, level + damp * trend)
        day = last_day + timedelta(days=h)
        f = base * w[day.weekday()]
        spread = 1.28 * sd * math.sqrt(1 + (h - 1) * a * a) * w[day.weekday()]  # ~80% interval
        out.append({"day": str(day), "value": round(f, 2), "lo": round(max(0.0, f - spread), 2), "hi": round(f + spread, 2)})
    return {"points": out, "params": {"alpha": a, "beta": b, "phi": phi}}


def backtest_wape(series, start_day, hold=14):
    """Weighted absolute % error when the model predicts the last `hold` days from earlier data."""
    if len(series) < hold + 28:
        return None
    train, test = series[:-hold], series[-hold:]
    fc = fit_forecast(train, start_day, hold)
    if not fc or sum(test) == 0:
        return None
    err = sum(abs(p["value"] - a) for p, a in zip(fc["points"], test))
    return round(err / sum(test) * 100, 1)


def forecast(scope="all", ref_id=None, horizon=30, metric="revenue"):
    horizon = horizon if horizon in (7, 15, 30, 90) else 30
    today = local_today()
    first = first_sale_day()
    if not first:
        return {"enough_data": False, "message": "No sales have been recorded yet, so no forecast can be made."}
    start = max(first, today - timedelta(days=180))
    history_days = (today - start).days + 1
    if history_days < 28:
        return {"enough_data": False,
                "message": f"Only {history_days} days of sales history. At least 28 days are needed for a forecast."}
    lines = sales_lines(start, today)
    key = None
    if scope == "category" and ref_id:
        db = get_db()
        sub_ids = {r["id"] for r in db.all("SELECT id FROM categories WHERE id=? OR parent_id=?", (ref_id, ref_id))}
        key = lambda r: r["category_id"] in sub_ids
    elif scope == "product" and ref_id:
        key = lambda r: r["product_id"] == ref_id
    value = "line_total" if metric == "revenue" else "qty"
    # forecast from complete days only (today is partial)
    series = daily_series(lines, start, today - timedelta(days=1), key, value)
    fc = fit_forecast(series, start, horizon)
    if not fc:
        return {"enough_data": False, "message": "Not enough history for this selection."}
    show = min(len(series), max(42, horizon * 2))
    hist = [{"day": str(start + timedelta(days=i)), "value": round(v, 2)} for i, v in enumerate(series)][-show:]
    total_fc = sum(p["value"] for p in fc["points"])
    total_lo = sum(p["lo"] for p in fc["points"])
    total_hi = sum(p["hi"] for p in fc["points"])
    last_same = sum(series[-horizon:]) if len(series) >= horizon else None
    nonzero = sum(1 for v in series[-60:] if v > 0)
    wape = backtest_wape(series, start)
    confidence = "low"
    if wape is not None and nonzero >= 30:
        confidence = "high" if wape < 25 else "medium" if wape < 45 else "low"
    return {
        "enough_data": True, "metric": metric, "horizon": horizon, "scope": scope, "ref_id": ref_id,
        "history": hist, "forecast": fc["points"],
        "summary": {"forecast_total": round(total_fc, 2), "range": [round(total_lo, 2), round(total_hi, 2)],
                    "previous_period_actual": round(last_same, 2) if last_same is not None else None,
                    "history_days": history_days, "active_days_last_60": nonzero,
                    "backtest_error_pct": wape, "confidence": confidence},
        "method": "Damped Holt exponential smoothing with weekday seasonality, fitted on recorded daily sales. "
                  "Range is an approximate 80% interval. Forecasts are estimates, not recorded sales.",
    }


# ------------------------------------------------------------------ demand analysis
def _pct(new, old):
    if old == 0:
        return None if new == 0 else 100.0
    return round((new - old) / old * 100, 1)


def insights():
    db = get_db()
    s = get_settings()
    lead = int(s["reorder_lead_days"])
    today = local_today()
    d30 = today - timedelta(days=29)
    d60 = today - timedelta(days=59)
    d90 = today - timedelta(days=89)
    lines = sales_lines(d90 - timedelta(days=90), today)  # 180 days for seasonality
    products = db.all("SELECT p.*, c.name AS category FROM products p LEFT JOIN categories c ON c.id=p.category_id "
                      "WHERE p.status <> 'draft'")
    cats = {c["id"]: c for c in db.all("SELECT id, name, parent_id FROM categories")}

    per = defaultdict(lambda: {"u30": 0, "u_prev30": 0, "u7": 0, "u28": 0, "u90": 0, "r30": 0.0, "r_prev30": 0.0,
                               "orders30": set(), "last_sale": None, "daily": defaultdict(float), "cogs90": 0.0})
    for r in lines:
        pid = r["product_id"]
        if pid is None:
            continue
        m = per[pid]
        age = (today - r["day"]).days
        if age < 30:
            m["u30"] += r["qty"]; m["r30"] += r["line_total"]; m["orders30"].add(r["order_id"])
        elif age < 60:
            m["u_prev30"] += r["qty"]; m["r_prev30"] += r["line_total"]
        if age < 7:
            m["u7"] += r["qty"]
        if age < 28:
            m["u28"] += r["qty"]
            m["daily"][r["day"]] += r["qty"]
        if age < 90:
            m["u90"] += r["qty"]; m["cogs90"] += (r["cost_price"] or 0) * r["qty"]
        if not m["last_sale"] or r["day"] > m["last_sale"]:
            m["last_sale"] = r["day"]

    act = defaultdict(lambda: {"views": 0, "carts": 0})
    for a in db.all("SELECT product_id, SUM(views) AS v, SUM(add_to_cart) AS c FROM activity_daily WHERE day >= ? GROUP BY product_id",
                    (str(d30),)):
        act[a["product_id"]] = {"views": a["v"] or 0, "carts": a["c"] or 0}
    stockouts = {r["product_id"]: r["n"] for r in db.all(
        "SELECT product_id, COUNT(*) AS n FROM stock_events WHERE kind='stockout' AND created_at >= ? GROUP BY product_id",
        (local_day_start_utc(d90),))}
    returns = defaultdict(int)
    cancels = defaultdict(int)
    for r in db.all("SELECT i.product_id, i.qty, o.status FROM order_items i JOIN orders o ON o.id=i.order_id "
                    "WHERE o.created_at >= ? AND o.status IN ('returned','refund_processing','refunded','cancelled','return_requested','return_in_progress')",
                    (local_day_start_utc(d90),)):
        if r["status"] == "cancelled":
            cancels[r["product_id"]] += r["qty"]
        else:
            ev = r["status"]
            if ev in ("returned", "return_requested", "return_in_progress"):
                returns[r["product_id"]] += r["qty"]
            else:
                # refund after cancel vs after return: check events
                returns[r["product_id"]] += 0
    # refunds that came from returns
    for r in db.all("SELECT i.product_id, i.qty FROM order_items i JOIN orders o ON o.id=i.order_id "
                    "WHERE o.created_at >= ? AND o.status IN ('refund_processing','refunded') AND EXISTS "
                    "(SELECT 1 FROM order_events e WHERE e.order_id=o.id AND e.status='returned')", (local_day_start_utc(d90),)):
        returns[r["product_id"]] += r["qty"]

    rows = []
    for p in products:
        m = per[p["id"]]
        avail = available(p)
        avg_daily = 0.5 * (m["u7"] / 7) + 0.5 * (m["u28"] / 28)
        daily_vals = [m["daily"].get(today - timedelta(days=i), 0) for i in range(1, 29)]
        sd = statistics.pstdev(daily_vals) if any(daily_vals) else 0
        cover = round(avail / avg_daily, 1) if avg_daily > 0 else None
        views, carts = act[p["id"]]["views"], act[p["id"]]["carts"]
        orders30 = len(m["orders30"])
        conv = round(orders30 / views * 100, 2) if views else None
        age_days = (today - local_date(p["created_at"])).days
        sold90 = m["u90"]
        safety = 1.65 * sd * math.sqrt(lead)
        reorder = max(0, math.ceil(avg_daily * (lead + 30) + safety - avail)) if avg_daily > 0 else 0
        turnover = round(sold90 / max(p["physical_stock"] + sold90 / 2, 1) * (365 / 90), 1) if sold90 else 0
        rows.append({
            "id": p["id"], "name": p["name"], "sku": p["sku"], "category": p["category"], "category_id": p["category_id"],
            "brand": p["brand"], "price": money(p["selling_price"]), "status": p["status"],
            "available": avail, "physical": p["physical_stock"], "reserved": p["reserved_qty"],
            "units_30": m["u30"], "units_prev_30": m["u_prev30"], "units_90": sold90,
            "revenue_30": money(m["r30"]), "revenue_prev_30": money(m["r_prev30"]),
            "growth_pct": _pct(m["u30"], m["u_prev30"]), "orders_30": orders30,
            "avg_daily": round(avg_daily, 2), "days_of_cover": cover, "reorder_qty": reorder,
            "last_sale": str(m["last_sale"]) if m["last_sale"] else None,
            "days_since_sale": (today - m["last_sale"]).days if m["last_sale"] else None,
            "age_days": age_days, "views_30": views, "carts_30": carts, "conversion_pct": conv,
            "cart_rate_pct": round(carts / views * 100, 1) if views else None,
            "stockouts_90": stockouts.get(p["id"], 0), "returns_90": returns[p["id"]], "cancels_90": cancels[p["id"]],
            "return_rate_pct": round(returns[p["id"]] / sold90 * 100, 1) if sold90 else None,
            "turnover_annual": turnover, "gross_margin_pct": round((p["selling_price"] - p["cost_price"]) / p["selling_price"] * 100, 1) if p["selling_price"] else None,
        })

    convs = sorted(r["conversion_pct"] for r in rows if r["conversion_pct"] is not None)
    med_conv = statistics.median(convs) if convs else None
    views_sorted = sorted(r["views_30"] for r in rows)
    v75 = views_sorted[int(len(views_sorted) * 0.75)] if views_sorted else 0

    def top(lst, key, n=8, rev=True):
        return sorted(lst, key=key, reverse=rev)[:n]

    groups = {
        "best_sellers": top([r for r in rows if r["units_30"] > 0], lambda r: r["revenue_30"]),
        "increasing": top([r for r in rows if (r["growth_pct"] or 0) >= 20 and r["units_30"] >= 5], lambda r: r["growth_pct"]),
        "declining": top([r for r in rows if r["growth_pct"] is not None and r["growth_pct"] <= -20 and r["units_prev_30"] >= 5],
                         lambda r: r["growth_pct"], rev=False),
        "low_sales": top([r for r in rows if r["units_30"] <= 2 and r["age_days"] >= 30 and r["status"] == "active"],
                         lambda r: r["available"]),
        "interest_low_conversion": top([r for r in rows if med_conv and r["views_30"] >= max(v75, 20)
                                        and r["conversion_pct"] is not None and r["conversion_pct"] < med_conv * 0.5],
                                       lambda r: r["views_30"]),
        "frequent_stockouts": top([r for r in rows if r["stockouts_90"] >= 2], lambda r: r["stockouts_90"]),
        "overstock_risk": top([r for r in rows if (r["days_of_cover"] and r["days_of_cover"] > 120)
                               or (r["avg_daily"] == 0 and r["available"] >= 20 and r["age_days"] >= 30)],
                              lambda r: r["available"]),
        "restock_soon": top([r for r in rows if r["avg_daily"] >= 0.1 and r["days_of_cover"] is not None
                             and r["days_of_cover"] <= lead + 7], lambda r: r["days_of_cover"], 12, rev=False),
    }

    # category demand
    cat_root = lambda cid: (cats[cid]["parent_id"] or cid) if cid in cats else None
    cat_stats = defaultdict(lambda: {"u30": 0, "u_prev30": 0, "r30": 0.0, "r_prev30": 0.0})
    for r in lines:
        root = cat_root(r["category_id"])
        if root is None:
            continue
        age = (today - r["day"]).days
        if age < 30:
            cat_stats[root]["u30"] += r["qty"]; cat_stats[root]["r30"] += r["line_total"]
        elif age < 60:
            cat_stats[root]["u_prev30"] += r["qty"]; cat_stats[root]["r_prev30"] += r["line_total"]
    categories = sorted([{"id": cid, "name": cats[cid]["name"], "units_30": v["u30"], "units_prev_30": v["u_prev30"],
                          "revenue_30": money(v["r30"]), "growth_pct": _pct(v["u30"], v["u_prev30"])}
                         for cid, v in cat_stats.items()], key=lambda x: -x["revenue_30"])

    # time patterns
    wd_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    wd = [0.0] * 7
    wd_days = [0] * 7
    for i in range(90):
        wd_days[(today - timedelta(days=i + 1)).weekday()] += 1
    weekly = defaultdict(float)
    monthly = defaultdict(float)
    for r in lines:
        age = (today - r["day"]).days
        if 1 <= age <= 90:
            wd[r["day"].weekday()] += r["line_total"]
        wk = r["day"] - timedelta(days=r["day"].weekday())
        weekly[str(wk)] += r["line_total"]
        monthly[r["day"].strftime("%Y-%m")] += r["line_total"]
    by_weekday = [{"day": wd_names[i], "avg_revenue": money(wd[i] / wd_days[i]) if wd_days[i] else 0} for i in range(7)]
    by_week = [{"week": k, "revenue": money(v)} for k, v in sorted(weekly.items())][-12:]
    by_month = [{"month": k, "revenue": money(v)} for k, v in sorted(monthly.items())][-6:]

    # funnel & search
    tot_views = sum(r["views_30"] for r in rows)
    tot_carts = sum(r["carts_30"] for r in rows)
    orders_30 = db.val(f"SELECT COUNT(*) FROM orders WHERE created_at >= ? AND status NOT IN ({EXCL})", (local_day_start_utc(d30),)) or 0
    searches = db.all("SELECT query, SUM(count) AS n, MIN(results) AS results FROM search_log WHERE day >= ? GROUP BY query ORDER BY n DESC LIMIT 15",
                      (str(d30),))
    zero = [x for x in searches if (x["results"] or 0) == 0]

    recs = recommendations(rows, groups, categories, by_weekday, med_conv, lead)
    first = first_sale_day()
    return {
        "generated_at": str(now_utc()), "data_window": {"from": str(d90), "to": str(today),
                                                        "first_sale": str(first) if first else None},
        "totals": {"products_analysed": len(rows), "units_30": sum(r["units_30"] for r in rows),
                   "revenue_30": money(sum(r["revenue_30"] for r in rows)),
                   "units_prev_30": sum(r["units_prev_30"] for r in rows),
                   "revenue_prev_30": money(sum(r["revenue_prev_30"] for r in rows))},
        "funnel": {"views_30": tot_views, "add_to_cart_30": tot_carts, "orders_30": orders_30,
                   "view_to_cart_pct": round(tot_carts / tot_views * 100, 1) if tot_views else None,
                   "view_to_order_pct": round(orders_30 / tot_views * 100, 2) if tot_views else None,
                   "median_product_conversion_pct": med_conv},
        "groups": groups, "categories": categories, "by_weekday": by_weekday, "by_week": by_week, "by_month": by_month,
        "searches": searches, "zero_result_searches": zero, "recommendations": recs, "products": rows,
        "lead_days": lead,
    }


def recommendations(rows, groups, categories, by_weekday, med_conv, lead):
    recs = []

    def add(kind, severity, msg, evidence, pid=None):
        recs.append({"kind": kind, "severity": severity, "message": msg, "evidence": evidence, "product_id": pid})

    for r in groups["restock_soon"][:8]:
        if r["available"] <= 0:
            msg = (f"{r['name']} is out of stock. Based on recent sales, consider ordering {r['reorder_qty']} units.")
        else:
            msg = (f"{r['name']} may run out of stock within {max(1, round(r['days_of_cover'])):g} days. Based on recent sales, "
                   f"consider ordering {r['reorder_qty']} more units.")
        add("restock", "high" if r["days_of_cover"] <= lead else "medium", msg,
            f"{r['available']} available, selling about {r['avg_daily']:g}/day; supplier lead time {lead} days.", r["id"])
    for r in groups["increasing"][:4]:
        add("growth", "info", f"{r['name']} sold {r['growth_pct']:g}% more units in the last 30 days than in the 30 days before.",
            f"{r['units_30']} units vs {r['units_prev_30']} units.", r["id"])
    cat_recs = 0
    for c in sorted(categories, key=lambda c: -abs(c["growth_pct"] or 0)):
        if cat_recs >= 4:
            break
        if c["growth_pct"] is not None and abs(c["growth_pct"]) >= 15:
            cat_recs += 1
        if c["growth_pct"] is not None and c["growth_pct"] >= 15 and c["units_30"] >= 10:
            add("category", "info", f"Demand for {c['name']} is increasing ({c['growth_pct']:+g}% units month on month).",
                f"{c['units_30']} units in the last 30 days vs {c['units_prev_30']}.")
        elif c["growth_pct"] is not None and c["growth_pct"] <= -20 and c["units_prev_30"] >= 10:
            add("category", "medium", f"Demand for {c['name']} has fallen {abs(c['growth_pct']):g}% month on month.",
                f"{c['units_30']} units in the last 30 days vs {c['units_prev_30']}.")
    for r in groups["declining"][:4]:
        caveat = " Part of this drop may be because it was out of stock." if (r["available"] <= 0 or r["stockouts_90"]) else ""
        add("decline", "medium", f"Sales of {r['name']} are down {abs(r['growth_pct']):g}% compared with the previous 30 days.{caveat}",
            f"{r['units_30']} units vs {r['units_prev_30']}.", r["id"])
    for r in groups["low_sales"][:4]:
        since = f"no sale in {r['days_since_sale']} days" if r["days_since_sale"] is not None else "no recorded sales"
        add("slow", "medium", f"{r['name']} has {r['available']} units in stock and {since}. Consider a promotion, bundle or price review.",
            f"{r['units_30']} units sold in 30 days; listed {r['age_days']} days ago.", r["id"])
    for r in groups["interest_low_conversion"][:3]:
        add("conversion", "medium", f"Consider reviewing the price or listing of {r['name']}: many shoppers view it but few buy.",
            f"{r['views_30']} views, {r['conversion_pct']}% conversion vs store median {med_conv}%.", r["id"])
    for r in groups["frequent_stockouts"][:3]:
        add("stockout", "high", f"{r['name']} went out of stock {r['stockouts_90']} times in 90 days. Raise its reorder level.",
            f"Average demand {r['avg_daily']:g}/day; current available {r['available']}.", r["id"])
    for r in groups["overstock_risk"][:3]:
        cover = f"about {r['days_of_cover']:g} days of stock" if r["days_of_cover"] else "stock but no recent sales"
        add("overstock", "low", f"{r['name']} may be overstocked: {cover} at the current sales rate.",
            f"{r['available']} available; {r['units_90']} sold in 90 days.", r["id"])
    for r in rows:
        if r["return_rate_pct"] and r["return_rate_pct"] >= 15 and r["units_90"] >= 8:
            add("returns", "medium", f"{r['name']} has a high return rate ({r['return_rate_pct']}%). Check quality or description accuracy.",
                f"{r['returns_90']} returned of {r['units_90']} sold in 90 days.", r["id"])
    if by_weekday and any(d["avg_revenue"] for d in by_weekday):
        best = max(by_weekday, key=lambda d: d["avg_revenue"])
        worst = min(by_weekday, key=lambda d: d["avg_revenue"])
        if worst["avg_revenue"] and best["avg_revenue"] / worst["avg_revenue"] >= 1.3:
            add("timing", "info", f"{best['day']} is the strongest sales day; {worst['day']} is the weakest.",
                f"Average revenue ₹{best['avg_revenue']:,.0f} vs ₹{worst['avg_revenue']:,.0f} over the last 90 days.")
    order = {"high": 0, "medium": 1, "info": 2, "low": 3}
    return sorted(recs, key=lambda x: order.get(x["severity"], 9))


# ------------------------------------------------------------------ optional LLM narrative
def ai_narrative(data):
    if not config.ANTHROPIC_API_KEY:
        return {"configured": False, "text": None,
                "message": "AI narrative is not configured (set ANTHROPIC_API_KEY). The statistical insights above are fully computed from your data."}
    compact = {
        "totals": data["totals"], "funnel": data["funnel"], "categories": data["categories"][:8],
        "recommendations": [{"message": r["message"], "evidence": r["evidence"]} for r in data["recommendations"][:15]],
        "best_sellers": [{k: r[k] for k in ("name", "units_30", "revenue_30", "growth_pct")} for r in data["groups"]["best_sellers"]],
    }
    prompt = ("You are a retail analyst for a small unit store. Write a short briefing (max 180 words, plain text, "
              "3-5 bullet points) for the owner using ONLY the figures in this JSON. Do not invent any numbers, "
              "products or causes; if something is uncertain, say so.\n\n" + json.dumps(compact))
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", method="POST",
                                 data=json.dumps({"model": config.ANTHROPIC_MODEL, "max_tokens": 600,
                                                  "messages": [{"role": "user", "content": prompt}]}).encode(),
                                 headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode())
        txt = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
        return {"configured": True, "text": txt}
    except (urllib.error.URLError, ValueError) as e:
        return {"configured": True, "text": None, "message": f"AI service unavailable: {e}"}
