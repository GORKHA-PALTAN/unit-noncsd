"""Inventory engine.

    Available = Physical stock - Reserved - Unavailable (damaged / quarantined)

Every change goes through a single conditional UPDATE so two customers can never take the same last
unit: the database only applies the reservation if enough stock is still available at that instant.
Each change writes an inventory_movements row (an audit trail of stock).
"""
from ..db import get_db, now_iso
from ..web import ApiError

MOVEMENT_TYPES = {
    "received": "New stock received",
    "reserved": "Reserved for order",
    "released": "Released after cancellation",
    "sold": "Sold / dispatched",
    "returned": "Returned to stock",
    "returned_damaged": "Returned (damaged)",
    "damaged": "Marked damaged",
    "damage_cleared": "Damaged units written off",
    "restored": "Unavailable units restored",
    "adjustment": "Manual adjustment",
}


def _log(db, product_id, mtype, qty, order_id=None, note=None, actor_id=None, at=None):
    p = db.one("SELECT physical_stock, reserved_qty, unavailable_qty FROM products WHERE id=?", (product_id,))
    db.insert("inventory_movements", {
        "product_id": product_id, "type": mtype, "qty": qty, "order_id": order_id, "note": note,
        "actor_id": actor_id, "physical_after": p["physical_stock"], "reserved_after": p["reserved_qty"],
        "unavailable_after": p["unavailable_qty"], "created_at": at or now_iso(),
    })
    if p["physical_stock"] - p["reserved_qty"] - p["unavailable_qty"] <= 0 and mtype in ("reserved", "damaged", "adjustment"):
        db.insert("stock_events", {"product_id": product_id, "kind": "stockout", "created_at": at or now_iso()})


def reserve(db, product_id, qty, order_id=None, at=None):
    """Atomically reserve qty units. Returns False if not enough available (nothing is changed)."""
    n = db.run(
        "UPDATE products SET reserved_qty = reserved_qty + ?, updated_at=? "
        "WHERE id=? AND status='active' AND (physical_stock - reserved_qty - unavailable_qty) >= ?",
        (qty, at or now_iso(), product_id, qty),
    )
    if n != 1:
        return False
    _log(db, product_id, "reserved", qty, order_id, at=at)
    return True


def release(db, product_id, qty, order_id=None, note=None, actor_id=None, at=None):
    db.run("UPDATE products SET reserved_qty = MAX(reserved_qty - ?, 0), updated_at=? WHERE id=?".replace(
        "MAX(", "GREATEST(" if _pg() else "MAX("), (qty, at or now_iso(), product_id))
    _log(db, product_id, "released", qty, order_id, note, actor_id, at)


def commit_sale(db, product_id, qty, order_id=None, actor_id=None, at=None):
    """Reserved units physically leave the store (dispatch)."""
    n = db.run(
        "UPDATE products SET physical_stock = physical_stock - ?, reserved_qty = reserved_qty - ?, "
        "units_sold = units_sold + ?, updated_at=? WHERE id=? AND reserved_qty >= ? AND physical_stock >= ?",
        (qty, qty, qty, at or now_iso(), product_id, qty, qty),
    )
    if n != 1:
        raise ApiError(409, "Stock records are inconsistent for this order; please review inventory.")
    _log(db, product_id, "sold", qty, order_id, actor_id=actor_id, at=at)


def restock_return(db, product_id, qty, order_id=None, damaged=False, actor_id=None, note=None, at=None):
    """Units come back after dispatch (return / failed delivery)."""
    if damaged:
        db.run("UPDATE products SET physical_stock = physical_stock + ?, unavailable_qty = unavailable_qty + ?, "
               "units_sold = units_sold - ?, updated_at=? WHERE id=?", (qty, qty, qty, at or now_iso(), product_id))
        _log(db, product_id, "returned_damaged", qty, order_id, note, actor_id, at)
    else:
        db.run("UPDATE products SET physical_stock = physical_stock + ?, units_sold = units_sold - ?, updated_at=? "
               "WHERE id=?", (qty, qty, at or now_iso(), product_id))
        _log(db, product_id, "returned", qty, order_id, note, actor_id, at)
    db.run("UPDATE products SET units_sold = 0 WHERE id=? AND units_sold < 0", (product_id,))


def admin_adjust(product_id, mtype, qty, note, actor_id):
    """Owner/staff stock operations. qty is always a positive number; adjustment can be +/-."""
    db = get_db()
    p = db.one("SELECT * FROM products WHERE id=?", (product_id,))
    if not p:
        raise ApiError(404, "Product not found.")
    avail = p["physical_stock"] - p["reserved_qty"] - p["unavailable_qty"]
    t = now_iso()
    if mtype == "received":
        if qty <= 0:
            raise ApiError(400, "Quantity received must be positive.")
        db.run("UPDATE products SET physical_stock = physical_stock + ?, updated_at=? WHERE id=?", (qty, t, product_id))
    elif mtype == "damaged":
        if qty <= 0 or qty > avail:
            raise ApiError(400, f"You can mark at most {avail} available units as damaged.")
        db.run("UPDATE products SET unavailable_qty = unavailable_qty + ?, updated_at=? WHERE id=?", (qty, t, product_id))
    elif mtype == "damage_cleared":
        if qty <= 0 or qty > p["unavailable_qty"]:
            raise ApiError(400, f"Only {p['unavailable_qty']} unavailable units can be written off.")
        db.run("UPDATE products SET unavailable_qty = unavailable_qty - ?, physical_stock = physical_stock - ?, updated_at=? "
               "WHERE id=?", (qty, qty, t, product_id))
    elif mtype == "restored":
        if qty <= 0 or qty > p["unavailable_qty"]:
            raise ApiError(400, f"Only {p['unavailable_qty']} unavailable units can be restored.")
        db.run("UPDATE products SET unavailable_qty = unavailable_qty - ?, updated_at=? WHERE id=?", (qty, t, product_id))
    elif mtype == "adjustment":
        if qty == 0:
            raise ApiError(400, "Adjustment cannot be zero.")
        if qty < 0 and -qty > avail:
            raise ApiError(400, f"Cannot remove more than the {avail} available units (reserved units belong to orders).")
        if not note:
            raise ApiError(400, "Please give a reason for a manual adjustment.")
        db.run("UPDATE products SET physical_stock = physical_stock + ?, updated_at=? WHERE id=?", (qty, t, product_id))
    else:
        raise ApiError(400, "Unknown stock operation.")
    _log(db, product_id, mtype, qty, note=note, actor_id=actor_id)
    return db.one("SELECT physical_stock, reserved_qty, unavailable_qty FROM products WHERE id=?", (product_id,))


def _pg():
    from ..db import IS_PG
    return IS_PG
