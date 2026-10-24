"""Cloudflare R2 photo storage (optional). Works with only the Python standard library.

R2 is an *extra* copy: the database copy of every photo is never removed by this code, so turning R2
on or off cannot lose a photo. If the R2 keys are not set, every function here quietly does nothing.
"""
import datetime
import hashlib
import hmac
import urllib.error
import urllib.parse
import urllib.request

from .. import config

TIMEOUT = 20


def enabled():
    return bool(config.R2_ACCOUNT_ID and config.R2_ACCESS_KEY_ID and config.R2_SECRET_ACCESS_KEY and config.R2_BUCKET)


def _base():
    return (getattr(config, "R2_ENDPOINT", None) or f"https://{config.R2_ACCOUNT_ID}.r2.cloudflarestorage.com").rstrip("/")


def _host():
    return _base().split("://", 1)[1]


def _sign(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _headers(method, canonical_uri, payload_hash, content_type=None, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    hdrs = {"host": _host(), "x-amz-content-sha256": payload_hash, "x-amz-date": amz}
    if content_type:
        hdrs["content-type"] = content_type
    names = sorted(hdrs)
    canonical = "\n".join([method, canonical_uri, "", "".join(f"{n}:{hdrs[n]}\n" for n in names),
                           ";".join(names), payload_hash])
    scope = f"{day}/auto/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    k = _sign(("AWS4" + config.R2_SECRET_ACCESS_KEY).encode(), day)
    for part in ("auto", "s3", "aws4_request"):
        k = _sign(k, part)
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    hdrs["authorization"] = (f"AWS4-HMAC-SHA256 Credential={config.R2_ACCESS_KEY_ID}/{scope}, "
                             f"SignedHeaders={';'.join(names)}, Signature={sig}")
    return hdrs


def _request(method, key, data=None, content_type=None):
    uri = "/" + urllib.parse.quote(config.R2_BUCKET + "/" + key, safe="/-_.~")
    payload_hash = hashlib.sha256(data or b"").hexdigest()
    hdrs = _headers(method, uri, payload_hash, content_type)
    hdrs.pop("host")
    req = urllib.request.Request(f"{_base()}{uri}", data=data, method=method, headers=hdrs)
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def put(key, data, mime):
    """Store a file. Returns True on success, False on any problem (never raises)."""
    if not enabled():
        return False
    try:
        with _request("PUT", key, data, mime):
            return True
    except Exception:  # noqa: BLE001
        return False


def get(key):
    """Return (mime, bytes) or None when the file is not in R2 (or R2 is unreachable)."""
    if not enabled():
        return None
    try:
        with _request("GET", key) as r:
            return r.headers.get("Content-Type") or "application/octet-stream", r.read()
    except Exception:  # noqa: BLE001
        return None


def exists(key):
    if not enabled():
        return False
    try:
        with _request("HEAD", key):
            return True
    except Exception:  # noqa: BLE001
        return False


def delete(key):
    if not enabled():
        return False
    try:
        with _request("DELETE", key):
            return True
    except Exception:  # noqa: BLE001
        return False


def check():
    """Used by the Settings page: write, read back and delete a tiny test file. Returns (ok, message)."""
    if not enabled():
        return False, "R2 keys are not set yet."
    key = "_check/test.txt"
    try:
        with _request("PUT", key, b"ok", "text/plain"):
            pass
        with _request("GET", key) as r:
            good = r.read() == b"ok"
        with _request("DELETE", key):
            pass
        return good, "R2 is working." if good else "R2 answered but the test file did not match."
    except urllib.error.HTTPError as e:
        hint = {403: "The keys were refused. Check the Access Key ID, Secret and that the token can write to this bucket.",
                404: "The bucket was not found. Check the bucket name and Account ID."}.get(e.code, f"R2 answered with error {e.code}.")
        return False, hint
    except Exception as e:  # noqa: BLE001
        return False, "Could not reach R2: " + str(e)[:120]
