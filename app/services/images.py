"""Shrink uploaded photos so the free database (Neon, 1 GB) lasts much longer.
Keeps the same file type (jpg stays jpg, png stays png), fixes phone rotation, and only keeps the smaller result."""
import io

try:
    from PIL import Image, ImageOps
except Exception:  # Pillow missing -> photos are saved exactly as uploaded
    Image = None

MAX_SIDE = {"products": 1200, "banners": 1600, "categories": 800, "vendors": 700}
SKIP_BELOW = 120 * 1024  # already small enough


def optimize(rel_path, mime, data, force=False):
    """Return (data, mime) — smaller if possible, otherwise unchanged."""
    if Image is None or mime not in ("image/jpeg", "image/png", "image/webp"):
        return data, mime
    if len(data) < SKIP_BELOW and not force:
        return data, mime
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        im = ImageOps.exif_transpose(im)
        side = MAX_SIDE.get(rel_path.split("/")[0], 1200)
        if max(im.size) > side:
            im.thumbnail((side, side), Image.LANCZOS)
        out = io.BytesIO()
        if mime == "image/jpeg":
            im.convert("RGB").save(out, "JPEG", quality=80, optimize=True, progressive=True)
        elif mime == "image/webp":
            im.save(out, "WEBP", quality=80, method=6)
        else:
            im.save(out, "PNG", optimize=True)
        new = out.getvalue()
        return (new, mime) if 0 < len(new) < len(data) else (data, mime)
    except Exception:
        return data, mime
