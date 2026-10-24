"""Owner tools to watch and save database storage (Neon free plan = 1 GB)."""
from .. import config
from ..db import IS_PG, get_db
from ..web import ApiError, api

LIMIT = 1024 * 1024 * 1024  # Neon free plan


def _usage(db):
    files = db.val("SELECT COALESCE(SUM(LENGTH(data)),0) FROM files") or 0
    count = db.val("SELECT COUNT(*) FROM files") or 0
    by = db.all("SELECT SUBSTR(path, 1, INSTR(path, '/') - 1) AS folder, COUNT(*) AS n, COALESCE(SUM(LENGTH(data)),0) AS bytes FROM files GROUP BY 1 ORDER BY 3 DESC") if not IS_PG else \
        db.all("SELECT split_part(path,'/',1) AS folder, COUNT(*) AS n, COALESCE(SUM(LENGTH(data)),0) AS bytes FROM files GROUP BY 1 ORDER BY 3 DESC")
    total = int(files)
    if IS_PG:
        try:
            total = int(db.val("SELECT pg_database_size(current_database())"))
        except Exception:
            pass
    big = db.val("SELECT COUNT(*) FROM files WHERE mime IN ('image/jpeg','image/png','image/webp') AND LENGTH(data) > ?", (400 * 1024,)) or 0
    try:
        from ..services import r2
        r2_on, r2_done = r2.enabled(), (db.val("SELECT COUNT(*) FROM r2_files") or 0)
    except Exception:  # noqa: BLE001  (r2.py or its table not there yet)
        r2_on, r2_done = False, 0
    return {"r2": {"enabled": r2_on, "copied": int(r2_done), "total": int(count)},
            "used": total, "is_pg": IS_PG, "files": int(files), "file_count": int(count), "limit": LIMIT, "big_images": int(big),
            "folders": [{"folder": r["folder"] or "other", "n": int(r["n"]), "bytes": int(r["bytes"])} for r in by]}


@api("GET", "/api/admin/storage", auth="owner")
def storage(ctx):
    return _usage(get_db())


@api("POST", "/api/admin/storage/shrink", auth="owner")
def storage_shrink(ctx):
    """Make photos that were uploaded earlier smaller (does a batch at a time)."""
    try:
        from ..services.images import optimize
    except ImportError:
        raise ApiError(500, "The photo-shrinking file (app/services/images.py) is missing on the server. Upload it to the app/services folder.")
    db = get_db()
    rows = db.all("SELECT id, path, mime FROM files WHERE mime IN ('image/jpeg','image/png','image/webp') AND LENGTH(data) > ? ORDER BY LENGTH(data) DESC LIMIT 15", (400 * 1024,))
    saved = done = 0
    for r in rows:
        row = db.one("SELECT data FROM files WHERE id=?", (r["id"],))
        old = bytes(row["data"])
        new, _ = optimize(r["path"], r["mime"], old)
        if len(new) < len(old):
            db.run("UPDATE files SET data=? WHERE id=?", (new, r["id"]))
            saved += len(old) - len(new)
            from ..services.common import copy_to_r2
            copy_to_r2(r["path"], r["mime"], new)  # keep R2 in step (does nothing if R2 is off)
            try:
                (config.UPLOAD_DIR / r["path"]).unlink()
            except OSError:
                pass
        else:
            # cannot be made smaller: mark by leaving as is (counted so the loop ends)
            pass
        done += 1
    left = _usage(db)["big_images"]
    return {"saved": saved, "done": done, "left": left, "stuck": left > 0 and saved == 0}


@api("POST", "/api/admin/storage/compact", auth="owner")
def storage_compact(ctx):
    """Hand the space freed by shrunk photos back to the database. (Postgres keeps old copies until it is compacted.)"""
    db = get_db()
    before = _usage(db)["used"]
    try:
        db.execute("VACUUM FULL files" if IS_PG else "VACUUM")
    except Exception as e:  # noqa: BLE001
        raise ApiError(500, "Could not compact the database right now: " + str(e)[:150])
    after = _usage(db)["used"]
    return {"before": before, "after": after, "freed": max(before - after, 0)}


@api("POST", "/api/admin/storage/r2-check", auth="owner")
def r2_check(ctx):
    """Test the Cloudflare R2 keys: writes, reads and removes a tiny test file."""
    from ..services import r2
    ok, message = r2.check()
    return {"ok": ok, "message": message}


@api("POST", "/api/admin/storage/r2-migrate", auth="owner")
def r2_migrate(ctx):
    """Copy existing photos to R2, a batch at a time. The database copies are never touched."""
    from ..services import r2
    from ..services.common import copy_to_r2
    if not r2.enabled():
        raise ApiError(400, "Cloudflare R2 is not set up yet. Add the four R2 settings in Render first.")
    db = get_db()
    rows = db.all("SELECT f.id, f.path, f.mime FROM files f WHERE NOT EXISTS (SELECT 1 FROM r2_files r WHERE r.path=f.path) "
                  "ORDER BY f.id LIMIT 15")
    copied = failed = 0
    for r in rows:
        row = db.one("SELECT data FROM files WHERE id=?", (r["id"],))
        if row and copy_to_r2(r["path"], r["mime"], bytes(row["data"])):
            copied += 1
        else:
            failed += 1
    left = db.val("SELECT COUNT(*) FROM files f WHERE NOT EXISTS (SELECT 1 FROM r2_files r WHERE r.path=f.path)") or 0
    return {"copied": copied, "failed": failed, "left": int(left), "stuck": failed > 0 and copied == 0}
