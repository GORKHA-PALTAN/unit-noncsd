"""Owner tools to watch and save database storage (Neon free plan = 1 GB)."""
from .. import config
from ..db import IS_PG, get_db
from ..services.images import optimize
from ..web import api

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
    return {"used": total, "files": int(files), "file_count": int(count), "limit": LIMIT, "big_images": int(big),
            "folders": [{"folder": r["folder"] or "other", "n": int(r["n"]), "bytes": int(r["bytes"])} for r in by]}


@api("GET", "/api/admin/storage", auth="owner")
def storage(ctx):
    return _usage(get_db())


@api("POST", "/api/admin/storage/shrink", auth="owner")
def storage_shrink(ctx):
    """Make photos that were uploaded earlier smaller (does a batch at a time)."""
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
