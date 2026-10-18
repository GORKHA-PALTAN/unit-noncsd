"""Database schema. Portable DDL: {PK} and {REAL} are swapped per database engine."""
from .db import IS_PG, get_db

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS companies (
  id {PK}, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, sort INTEGER DEFAULT 0, active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS rank_categories (
  id {PK}, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, sort INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS buyers (
  id {PK}, code TEXT UNIQUE NOT NULL, company_code TEXT NOT NULL, category_code TEXT NOT NULL,
  seniority INTEGER NOT NULL, real_name TEXT, user_id INTEGER, active INTEGER DEFAULT 1,
  is_sample INTEGER DEFAULT 0, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id {PK}, name TEXT NOT NULL, email TEXT UNIQUE, phone TEXT, password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'customer', permissions TEXT DEFAULT '[]', status TEXT NOT NULL DEFAULT 'active',
  buyer_id INTEGER REFERENCES buyers(id), is_sample INTEGER DEFAULT 0,
  failed_logins INTEGER DEFAULT 0, locked_until TEXT, created_at TEXT NOT NULL, last_login_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_users_role ON users(role);

CREATE TABLE IF NOT EXISTS sessions (
  id {PK}, token_hash TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, ip TEXT, ua TEXT
);

CREATE TABLE IF NOT EXISTS addresses (
  id {PK}, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, label TEXT, name TEXT NOT NULL,
  phone TEXT NOT NULL, line1 TEXT NOT NULL, line2 TEXT, city TEXT NOT NULL, state TEXT NOT NULL,
  pincode TEXT NOT NULL, is_default INTEGER DEFAULT 0, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
  id {PK}, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, parent_id INTEGER REFERENCES categories(id),
  department TEXT, icon TEXT, color TEXT, sort INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
  default_tax_rate {REAL} DEFAULT 18, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
  id {PK}, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, description TEXT,
  category_id INTEGER REFERENCES categories(id), subcategory_id INTEGER REFERENCES categories(id),
  brand TEXT, sku TEXT UNIQUE NOT NULL,
  cost_price {REAL} NOT NULL DEFAULT 0, selling_price {REAL} NOT NULL, mrp {REAL},
  tax_rate {REAL} DEFAULT 18,
  physical_stock INTEGER NOT NULL DEFAULT 0, reserved_qty INTEGER NOT NULL DEFAULT 0,
  unavailable_qty INTEGER NOT NULL DEFAULT 0, units_sold INTEGER NOT NULL DEFAULT 0,
  low_stock_threshold INTEGER DEFAULT 10, max_per_order INTEGER DEFAULT 10,
  rating_avg {REAL} DEFAULT 0, rating_count INTEGER DEFAULT 0,
  specs TEXT DEFAULT '{}', weight_g INTEGER, dimensions TEXT, shipping_req TEXT,
  status TEXT NOT NULL DEFAULT 'draft', featured INTEGER DEFAULT 0, is_sample INTEGER DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  CHECK (reserved_qty >= 0), CHECK (physical_stock >= 0), CHECK (unavailable_qty >= 0)
);
CREATE INDEX IF NOT EXISTS ix_products_cat ON products(category_id);
CREATE INDEX IF NOT EXISTS ix_products_status ON products(status);

CREATE TABLE IF NOT EXISTS product_images (
  id {PK}, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE, url TEXT NOT NULL, sort INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cart_items (
  id {PK}, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE, qty INTEGER NOT NULL,
  added_at TEXT NOT NULL, UNIQUE(user_id, product_id)
);
CREATE TABLE IF NOT EXISTS wishlist (
  id {PK}, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE, added_at TEXT NOT NULL,
  UNIQUE(user_id, product_id)
);

CREATE TABLE IF NOT EXISTS delivery_methods (
  id {PK}, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, description TEXT, charge {REAL} DEFAULT 0,
  free_above {REAL}, eta_min_days INTEGER DEFAULT 2, eta_max_days INTEGER DEFAULT 5, active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS coupons (
  id {PK}, code TEXT UNIQUE NOT NULL, description TEXT, kind TEXT NOT NULL DEFAULT 'pct', value {REAL} NOT NULL,
  min_order {REAL} DEFAULT 0, max_discount {REAL}, starts_at TEXT, ends_at TEXT, usage_limit INTEGER,
  used_count INTEGER DEFAULT 0, active INTEGER DEFAULT 1, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
  id {PK}, order_no TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id),
  buyer_code TEXT, buyer_company TEXT, buyer_category TEXT,
  status TEXT NOT NULL, payment_method TEXT NOT NULL, payment_status TEXT NOT NULL,
  mrp_total {REAL} DEFAULT 0, subtotal {REAL} NOT NULL, coupon_code TEXT, coupon_discount {REAL} DEFAULT 0,
  delivery_method TEXT, delivery_charge {REAL} DEFAULT 0, tax_total {REAL} DEFAULT 0, grand_total {REAL} NOT NULL,
  cost_total {REAL} DEFAULT 0,
  ship_name TEXT, ship_phone TEXT, ship_address TEXT,
  est_delivery_from TEXT, est_delivery_to TEXT, courier TEXT, tracking_no TEXT,
  cancel_reason TEXT, stock_state TEXT NOT NULL DEFAULT 'reserved',
  is_sample INTEGER DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  paid_at TEXT, dispatched_at TEXT, delivered_at TEXT, payment_expires_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS ix_orders_created ON orders(created_at);
CREATE INDEX IF NOT EXISTS ix_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS order_items (
  id {PK}, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id INTEGER REFERENCES products(id) ON DELETE SET NULL, name TEXT NOT NULL, sku TEXT,
  unit_price {REAL} NOT NULL, mrp {REAL}, cost_price {REAL} DEFAULT 0, tax_rate {REAL} DEFAULT 0,
  qty INTEGER NOT NULL, line_total {REAL} NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS ix_items_product ON order_items(product_id);

CREATE TABLE IF NOT EXISTS order_events (
  id {PK}, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE, status TEXT NOT NULL,
  note TEXT, actor_id INTEGER, visible INTEGER DEFAULT 1, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_order ON order_events(order_id);

CREATE TABLE IF NOT EXISTS payments (
  id {PK}, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE, method TEXT NOT NULL,
  provider_order_id TEXT, provider_payment_id TEXT, amount {REAL} NOT NULL, status TEXT NOT NULL,
  error TEXT, token_nonce TEXT, created_at TEXT NOT NULL, verified_at TEXT
);

CREATE TABLE IF NOT EXISTS return_requests (
  id {PK}, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE, user_id INTEGER NOT NULL,
  kind TEXT NOT NULL, reason TEXT, status TEXT NOT NULL DEFAULT 'pending', prev_status TEXT,
  resolution_note TEXT, restock INTEGER DEFAULT 1, created_at TEXT NOT NULL, resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS refunds (
  id {PK}, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE, amount {REAL} NOT NULL,
  status TEXT NOT NULL DEFAULT 'processing', method TEXT, reference TEXT, note TEXT,
  created_at TEXT NOT NULL, completed_at TEXT
);

CREATE TABLE IF NOT EXISTS inventory_movements (
  id {PK}, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE, type TEXT NOT NULL,
  qty INTEGER NOT NULL, order_id INTEGER, note TEXT, actor_id INTEGER,
  physical_after INTEGER, reserved_after INTEGER, unavailable_after INTEGER, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mov_product ON inventory_movements(product_id);

CREATE TABLE IF NOT EXISTS reviews (
  id {PK}, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, order_id INTEGER,
  rating INTEGER NOT NULL, title TEXT, body TEXT, status TEXT DEFAULT 'published', created_at TEXT NOT NULL,
  UNIQUE(product_id, user_id)
);

CREATE TABLE IF NOT EXISTS notifications (
  id {PK}, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, title TEXT NOT NULL,
  body TEXT, link TEXT, is_read INTEGER DEFAULT 0, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_notif_user ON notifications(user_id);

CREATE TABLE IF NOT EXISTS banners (
  id {PK}, title TEXT NOT NULL, subtitle TEXT, cta TEXT, link TEXT, theme TEXT DEFAULT 'navy',
  image_url TEXT, placement TEXT DEFAULT 'hero', department TEXT, active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS expenses (
  id {PK}, date TEXT NOT NULL, category TEXT NOT NULL, amount {REAL} NOT NULL, note TEXT,
  is_sample INTEGER DEFAULT 0, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_daily (
  id {PK}, day TEXT NOT NULL, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  views INTEGER DEFAULT 0, add_to_cart INTEGER DEFAULT 0, wishlist INTEGER DEFAULT 0,
  UNIQUE(day, product_id)
);
CREATE TABLE IF NOT EXISTS search_log (
  id {PK}, day TEXT NOT NULL, query TEXT NOT NULL, results INTEGER DEFAULT 0, count INTEGER DEFAULT 1,
  UNIQUE(day, query)
);
CREATE TABLE IF NOT EXISTS stock_events (
  id {PK}, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE, kind TEXT NOT NULL, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
  id {PK}, path TEXT UNIQUE NOT NULL, mime TEXT NOT NULL, data {BLOB} NOT NULL, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_codes (
  id {PK}, email TEXT NOT NULL, code_hash TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  ip TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_login_codes_email ON login_codes(email);

CREATE TABLE IF NOT EXISTS audit_log (
  id {PK}, actor_id INTEGER, action TEXT NOT NULL, entity TEXT, entity_id TEXT, detail TEXT, ip TEXT, created_at TEXT NOT NULL
);
"""


def create_schema():
    db = get_db()
    ddl = SCHEMA.replace("{PK}", "BIGSERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT")
    ddl = ddl.replace("{REAL}", "DOUBLE PRECISION" if IS_PG else "REAL").replace("{BLOB}", "BYTEA" if IS_PG else "BLOB")
    for stmt in ddl.split(";"):
        if stmt.strip():
            db.execute(stmt)
