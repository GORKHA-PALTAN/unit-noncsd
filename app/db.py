"""Thin database layer over SQLite (default) or PostgreSQL (psycopg 3).

All SQL in the app uses '?' placeholders and portable types; the adapter converts for Postgres.
Writes that touch stock, payments or orders run inside `transaction()` so they commit or roll back together.
"""
import json
import sqlite3
from decimal import Decimal
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from . import config

IS_PG = config.DATABASE_URL.startswith(("postgres://", "postgresql://"))
_local = threading.local()


class DB:
    def __init__(self, raw):
        self.raw = raw
        self.in_tx = False

    def _sql(self, sql):
        return sql.replace("%", "%%").replace("?", "%s") if IS_PG else sql

    def execute(self, sql, params=()):
        try:
            cur = self.raw.cursor()
            cur.execute(self._sql(sql), tuple(params))
            return cur
        except Exception:
            # Cloud databases (e.g. Neon) close idle connections. Reconnect once, unless mid-transaction.
            if IS_PG and not self.in_tx and (getattr(self.raw, "closed", False) or getattr(self.raw, "broken", False)):
                self.raw = _connect().raw
                cur = self.raw.cursor()
                cur.execute(self._sql(sql), tuple(params))
                return cur
            raise

    def all(self, sql, params=()):
        cur = self.execute(sql, params)
        if cur.description is None:
            return []
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        if IS_PG:  # PostgreSQL returns NUMERIC as Decimal and BYTEA as memoryview
            rows = [tuple(float(v) if isinstance(v, Decimal) else (bytes(v) if isinstance(v, memoryview) else v) for v in r) for r in rows]
        return [dict(zip(cols, row)) for row in rows]

    def one(self, sql, params=()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def val(self, sql, params=()):
        cur = self.execute(sql, params)
        row = cur.fetchone()
        v = row[0] if row else None
        return float(v) if isinstance(v, Decimal) else v

    def run(self, sql, params=()):
        """Execute a write and return affected row count."""
        return self.execute(sql, params).rowcount

    def insert(self, table, data):
        cols = list(data.keys())
        sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) RETURNING id"
        cur = self.execute(sql, [data[c] for c in cols])
        return cur.fetchone()[0]

    def update(self, table, row_id, data):
        if not data:
            return 0
        sets = ",".join(f"{k}=?" for k in data)
        return self.run(f"UPDATE {table} SET {sets} WHERE id=?", list(data.values()) + [row_id])


def _connect():
    if IS_PG:
        import psycopg  # type: ignore  # optional dependency: pip install "psycopg[binary]"
        raw = psycopg.connect(config.DATABASE_URL, autocommit=True, prepare_threshold=None)
        return DB(raw)
    path = config.DATABASE_URL.replace("sqlite:///", "", 1)
    raw = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA foreign_keys=ON")
    raw.execute("PRAGMA busy_timeout=15000")
    return DB(raw)


def get_db():
    """One connection per worker thread (connections are reused, transactions are explicit)."""
    db = getattr(_local, "db", None)
    if db is None:
        db = _connect()
        _local.db = db
    return db


@contextmanager
def transaction(db=None):
    db = db or get_db()
    if db.in_tx:  # nested: join outer transaction
        yield db
        return
    db.execute("BEGIN IMMEDIATE" if not IS_PG else "BEGIN")
    db.in_tx = True
    try:
        yield db
        db.execute("COMMIT")
    except BaseException:
        try:
            db.execute("ROLLBACK")
        finally:
            db.in_tx = False
        raise
    db.in_tx = False


# ---------- time helpers (stored as UTC ISO strings; business days use local offset) ----------
LOCAL_TZ = timezone(timedelta(minutes=config.TZ_OFFSET_MINUTES))


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def now_iso():
    return iso(now_utc())


def parse_iso(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def local_date(s_or_dt):
    dt = parse_iso(s_or_dt) if isinstance(s_or_dt, str) else s_or_dt
    return dt.astimezone(LOCAL_TZ).date()


def local_today():
    return now_utc().astimezone(LOCAL_TZ).date()


def local_day_start_utc(d):
    """UTC ISO string for 00:00 local time on date d."""
    dt = datetime(d.year, d.month, d.day, tzinfo=LOCAL_TZ)
    return iso(dt)


def jdump(v):
    return json.dumps(v, ensure_ascii=False)


def jload(s, default=None):
    if s in (None, ""):
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default
