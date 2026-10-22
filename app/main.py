"""Application entry point: wires routes, static files, security headers and background jobs."""
import asyncio
import contextlib

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import config
from .db import get_db
from .schema import create_schema
from .web import ROUTES, ApiError

# importing registers the routes
from .routes import auth, store, admin, vendor, item_returns, storage  # noqa: F401,E402


CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://accounts.google.com/gsi/style; "
       "font-src 'self' https://fonts.gstatic.com data:; script-src 'self' https://checkout.razorpay.com https://accounts.google.com/gsi/client; "
       "frame-src https://api.razorpay.com https://checkout.razorpay.com https://accounts.google.com; "
       "connect-src 'self' https://lumberjack.razorpay.com https://accounts.google.com/gsi/; "
       "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


LAST_ACTIVITY = [0.0]  # time of the last real visitor request (health checks excluded)


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path != "/health":
            import time
            LAST_ACTIVITY[0] = time.monotonic()
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        resp.headers.setdefault("Content-Security-Policy", CSP)
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        elif request.url.path.startswith("/static/"):
            # Always check for a newer file (cheap 304 when unchanged) so updates show up without a hard refresh
            resp.headers.setdefault("Cache-Control", "no-cache")
        if request.url.path.startswith("/uploads/") and request.url.path.endswith(".svg"):
            resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
        return resp


def store_page(request):
    return FileResponse(config.STATIC_DIR / "store" / "index.html", headers={"Cache-Control": "no-cache"})


def admin_page(request):
    return FileResponse(config.STATIC_DIR / "admin" / "index.html", headers={"Cache-Control": "no-cache"})


def _static_file(path, mime, cache="no-cache"):
    async def handler(request):
        return FileResponse(config.STATIC_DIR / path, media_type=mime, headers={"Cache-Control": cache})
    return handler


def vendor_page(request):
    return FileResponse(config.STATIC_DIR / "vendor" / "index.html", headers={"Cache-Control": "no-cache"})


async def health(request):
    return JSONResponse({"ok": True, "app": config.APP_NAME})


async def razorpay_webhook(request: Request):
    from .services.payments import handle_webhook
    raw = await request.body()
    try:
        out = await run_in_threadpool(handle_webhook, raw, request.headers.get("x-razorpay-signature"))
        return JSONResponse(out)
    except ApiError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)


UPLOAD_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml", ".mp4": "video/mp4", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".wav": "audio/wav", ".webm": "video/webm"}


async def uploads(request):
    """Serve product images from the local cache, falling back to the database copy."""
    import re
    from starlette.responses import Response
    rel = request.path_params["path"]
    if not re.fullmatch(r"[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-.]+)+", rel) or ".." in rel:
        return PlainTextResponse("Not found", status_code=404)
    disk = config.UPLOAD_DIR / rel
    if disk.is_file():
        return FileResponse(disk, headers={"Cache-Control": "public, max-age=86400"})
    from .services.common import load_file
    found = await run_in_threadpool(load_file, rel)
    if not found:
        return PlainTextResponse("Not found", status_code=404)
    mime, data = found
    try:
        disk.parent.mkdir(parents=True, exist_ok=True)
        disk.write_bytes(data)  # re-create the cache
        return FileResponse(disk, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})
    except OSError:
        pass
    return Response(data, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})


async def not_found_api(request):
    return JSONResponse({"error": "Not found."}, status_code=404)


def _startup():
    from .seed import ensure_base, seed_sample
    create_schema()
    owner = ensure_base()
    seeded = False
    if config.SEED_SAMPLE_DATA:
        from .db import IS_PG
        if IS_PG:
            # On a cloud database the sample data takes a few minutes; build it in the background so the
            # server starts answering immediately (the store fills in once it finishes).
            import threading

            def _bg():
                try:
                    if seed_sample():
                        print("Sample catalogue and demo order history created (marked SAMPLE).")
                except Exception as e:
                    print("Sample data setup failed:", e)
            threading.Thread(target=_bg, daemon=True).start()
        else:
            seeded = seed_sample()
    if owner:
        email, pw, generated = owner
        msg = (f"\n{'=' * 64}\n  OWNER ACCOUNT CREATED\n  Email:    {email}\n  Password: {pw if generated else '(from OWNER_PASSWORD in .env)'}\n"
               f"  Sign in at http://127.0.0.1:{config.PORT}/admin\n{'=' * 64}\n")
        print(msg)
        if generated:
            (config.BASE_DIR / "data" / "FIRST_RUN_OWNER_LOGIN.txt").write_text(
                msg + "\nChange this password after signing in (Account menu) and then delete this file.\n", encoding="utf-8")
    if seeded:
        print("Sample catalogue and demo order history created (marked SAMPLE).")


async def _expiry_loop():
    from .services.orders import expire_stale_payments
    import time
    while True:
        await asyncio.sleep(60)
        # Only touch the database while people are using the store, so a cloud database can sleep when idle.
        if time.monotonic() - LAST_ACTIVITY[0] > 900:
            continue
        try:
            await run_in_threadpool(expire_stale_payments)
        except Exception as e:  # keep the loop alive
            print("Payment expiry job error:", e)


@contextlib.asynccontextmanager
async def lifespan(app):
    (config.BASE_DIR / "data").mkdir(exist_ok=True)
    (config.UPLOAD_DIR / "products").mkdir(parents=True, exist_ok=True)
    (config.UPLOAD_DIR / "sample").mkdir(parents=True, exist_ok=True)
    await run_in_threadpool(_startup)
    task = asyncio.create_task(_expiry_loop())
    yield
    task.cancel()


for _d in (config.BASE_DIR / "data", config.UPLOAD_DIR / "products", config.UPLOAD_DIR / "sample", config.STATIC_DIR / "common"):
    _d.mkdir(parents=True, exist_ok=True)

routes = [
    Route("/", store_page),
    Route("/admin", admin_page),
    Route("/admin/", admin_page),
    Route("/vendor", vendor_page),
    Route("/manifest.webmanifest", _static_file("store/manifest.webmanifest", "application/manifest+json")),
    Route("/vendor.webmanifest", _static_file("vendor/manifest.webmanifest", "application/manifest+json")),
    Route("/sw.js", _static_file("store/sw.js", "text/javascript")),
    Route("/vendor/", vendor_page),
    Route("/health", health),
    Route("/api/payments/razorpay/webhook", razorpay_webhook, methods=["POST"]),
    *ROUTES,
    Route("/api/{rest:path}", not_found_api, methods=["GET", "POST", "PUT", "PATCH", "DELETE"]),
    Mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static"),
    Route("/uploads/{path:path}", uploads),
]

app = Starlette(debug=config.DEBUG, routes=routes, middleware=[Middleware(SecurityHeaders)], lifespan=lifespan,
                max_body_size=12 * 1024 * 1024)
