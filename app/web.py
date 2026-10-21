"""Small routing layer on top of Starlette.

Handlers are plain (sync) functions `def handler(ctx)`; they run in a worker thread so database
work never blocks the event loop. The wrapper enforces authentication, role permissions, CSRF and
rate limits *before* the handler runs.
"""
import json
import traceback

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import config
from .security import has_perm, load_session, rate_limited

ROUTES = []
SESSION_COOKIE = "ncsd_sid"


class ApiError(Exception):
    def __init__(self, status, message, extra=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra or {}


class Ctx:
    def __init__(self, request, body, user, csrf, form=None):
        self.request = request
        self.body = body if isinstance(body, dict) else {}
        self.raw_body = body
        self.user = user
        self.csrf = csrf
        self.form = form
        self.params = request.path_params
        self.query = request.query_params
        self.ip = client_ip(request)
        self.set_cookies = []
        self.delete_cookies = []

    @property
    def uid(self):
        return self.user["id"] if self.user else None

    def q(self, name, default=None):
        v = self.query.get(name)
        return v if v not in (None, "") else default

    def qint(self, name, default=None, lo=None, hi=None):
        v = self.q(name)
        try:
            v = int(v) if v is not None else default
        except ValueError:
            v = default
        if v is not None and lo is not None:
            v = max(lo, v)
        if v is not None and hi is not None:
            v = min(hi, v)
        return v

    def get(self, name, default=None):
        return self.body.get(name, default)

    def require(self, *names):
        missing = [n for n in names if self.body.get(n) in (None, "")]
        if missing:
            raise ApiError(400, f"Missing required field: {', '.join(missing)}")
        return [self.body[n] for n in names]


def client_ip(request):
    return request.client.host if request.client else "unknown"


def api(method, path, auth=None, perm=None, limit=None, multipart=False):
    """auth: None (public) | 'user' (any signed-in) | 'customer' | 'admin' (owner/staff) | 'owner'."""
    def deco(fn):
        async def endpoint(request: Request):
            token = request.cookies.get(SESSION_COOKIE)
            user, csrf = (None, None)
            if token:
                user, csrf = await run_in_threadpool(load_session, token)

            # Rate limit
            key = limit or ("read" if method == "GET" else "write")
            wait = rate_limited(key, client_ip(request))
            if wait:
                return JSONResponse({"error": f"Too many requests. Try again in {wait}s."}, status_code=429,
                                    headers={"Retry-After": str(wait)})

            # Auth / role checks
            if auth and not user:
                return JSONResponse({"error": "Please sign in to continue.", "code": "auth_required"}, status_code=401)
            if auth == "customer" and user["role"] != "customer":
                return JSONResponse({"error": "This action is available to customer accounts only."}, status_code=403)
            if auth == "admin" and user["role"] not in ("owner", "staff"):
                return JSONResponse({"error": "Admin access required."}, status_code=403)
            if auth == "vendor" and user["role"] != "vendor":
                return JSONResponse({"error": "Vendor access required."}, status_code=403)
            if auth == "owner" and user["role"] != "owner":
                return JSONResponse({"error": "Only the owner can do this."}, status_code=403)
            if perm and not has_perm(user, perm):
                return JSONResponse({"error": "You do not have permission for this section."}, status_code=403)

            # CSRF: mutating requests from signed-in users must echo the session's CSRF token
            if method != "GET":
                if user and request.headers.get("x-csrf-token") != csrf:
                    return JSONResponse({"error": "Security token mismatch. Refresh the page and try again."},
                                        status_code=403)
                if not user and request.headers.get("x-requested-with") != "fetch":
                    return JSONResponse({"error": "Invalid request."}, status_code=403)

            body, form = {}, None
            if method in ("POST", "PUT", "PATCH", "DELETE"):
                if multipart:
                    form = await request.form(max_files=10, max_fields=50)
                else:
                    raw = await request.body()
                    if raw:
                        if len(raw) > 2_000_000:
                            return JSONResponse({"error": "Request too large."}, status_code=413)
                        try:
                            body = json.loads(raw)
                        except ValueError:
                            return JSONResponse({"error": "Invalid JSON body."}, status_code=400)
            ctx = Ctx(request, body, user, csrf, form)
            try:
                result = await run_in_threadpool(fn, ctx)
            except ApiError as e:
                return JSONResponse({"error": e.message, **e.extra}, status_code=e.status)
            except Exception:  # never leak internals
                traceback.print_exc()
                return JSONResponse({"error": "Something went wrong on the server. Please try again."}, status_code=500)
            finally:
                if form is not None:
                    await form.close()
            resp = result if isinstance(result, Response) else JSONResponse(result if result is not None else {"ok": True})
            for name, value, max_age in ctx.set_cookies:
                resp.set_cookie(name, value, max_age=max_age, httponly=True, samesite="lax",
                                secure=config.COOKIE_SECURE, path="/")
            for name in ctx.delete_cookies:
                resp.delete_cookie(name, path="/")
            return resp

        ROUTES.append(Route(path, endpoint, methods=[method]))
        return fn
    return deco


# ---------------- validation helpers ----------------
def num(v, name, lo=None, hi=None, integer=False, required=True):
    if v in (None, ""):
        if required:
            raise ApiError(400, f"{name} is required.")
        return None
    try:
        n = int(v) if integer else float(v)
    except (TypeError, ValueError):
        raise ApiError(400, f"{name} must be a number.")
    if integer and float(v) != int(v):
        raise ApiError(400, f"{name} must be a whole number.")
    if lo is not None and n < lo:
        raise ApiError(400, f"{name} must be at least {lo}.")
    if hi is not None and n > hi:
        raise ApiError(400, f"{name} must be at most {hi}.")
    return n


def text(v, name, required=True, max_len=500, min_len=0):
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise ApiError(400, f"{name} is required.")
        return None
    if not isinstance(v, (str, int, float)):
        raise ApiError(400, f"{name} is invalid.")
    s = str(v).strip()
    if len(s) > max_len:
        raise ApiError(400, f"{name} is too long (max {max_len} characters).")
    if len(s) < min_len:
        raise ApiError(400, f"{name} is too short.")
    return s


def page_args(ctx, default_per=20, max_per=100):
    page = ctx.qint("page", 1, lo=1)
    per = ctx.qint("per", default_per, lo=1, hi=max_per)
    return page, per, (page - 1) * per
