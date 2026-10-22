"""Application configuration. Values come from environment variables or a local .env file.
Secrets (payment keys, AI keys, owner password) must never be placed in frontend code."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv():
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), val)


_load_dotenv()


def env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def env_bool(name, default=False):
    v = env(name)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


APP_NAME = env("APP_NAME", "PVC Paltan Store")
HOST = env("HOST", "0.0.0.0")  # 0.0.0.0 = reachable from phones on the same Wi-Fi; 127.0.0.1 = this computer only
PORT = int(env("PORT", "8000"))
DEBUG = env_bool("DEBUG", False)

# Database: SQLite file by default; set DATABASE_URL=postgresql://user:pass@host/db for PostgreSQL
def _clean_db_url(v):
    """Accept the connection line exactly as copied from Neon, even with a leading `psql` or quotes."""
    v = (v or "").strip()
    if v.lower().startswith("psql "):
        v = v[5:].strip()
    v = v.strip("'\" ")
    if v.startswith("postgres://"):
        v = "postgresql://" + v[len("postgres://"):]
    return v


DATABASE_URL = _clean_db_url(env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'store.db'}"))

# Security
SESSION_DAYS = int(env("SESSION_DAYS", "7"))
COOKIE_SECURE = env_bool("COOKIE_SECURE", False)  # set true when served over HTTPS
SECRET_KEY = env("SECRET_KEY")  # used to sign sandbox payment tokens; auto-generated if missing

OWNER_EMAIL = env("OWNER_EMAIL", "owner@unit.local")
OWNER_PASSWORD = env("OWNER_PASSWORD")  # if missing on first run a random one is generated and printed
OWNER_NAME = env("OWNER_NAME", "Store Owner")

SEED_SAMPLE_DATA = env_bool("SEED_SAMPLE_DATA", True)
# Demo logins with published passwords (customer@demo.local, clerk@unit.local). Turn off on a public server.
SEED_DEMO_ACCOUNTS = env_bool("SEED_DEMO_ACCOUNTS", True)
# Permanent public address of the store (Render sets RENDER_EXTERNAL_URL automatically)
PUBLIC_URL = (env("PUBLIC_URL") or env("RENDER_EXTERNAL_URL") or "").rstrip("/")
RATE_LIMIT_SCALE = float(env("RATE_LIMIT_SCALE", "1"))  # >1 relaxes limits (automated tests only)

# Business time zone (India Standard Time = +330 minutes)
TZ_OFFSET_MINUTES = int(env("TZ_OFFSET_MINUTES", "330"))

# Payments
RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET")
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET")

# "Continue with Google" for customers: OAuth Client ID from Google Cloud Console (not secret)
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID")

# Optional AI narrative (statistical analytics work without it)
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", "claude-sonnet-4-5")

# Email (order updates and login codes). On Render's free plan SMTP is blocked, so use Brevo's
# HTTPS API: BREVO_API_KEY plus MAIL_FROM_EMAIL (a sender address verified in Brevo).
BREVO_API_KEY = env("BREVO_API_KEY")
# Or send from your own Gmail through a Google Apps Script web app (see DEPLOY-ONLINE.md)
GMAIL_SCRIPT_URL = env("GMAIL_SCRIPT_URL")
GMAIL_SCRIPT_SECRET = env("GMAIL_SCRIPT_SECRET")
MAIL_FROM_EMAIL = env("MAIL_FROM_EMAIL")
MAIL_FROM_NAME = env("MAIL_FROM_NAME")
OTP_MINUTES = int(env("OTP_MINUTES", "10"))
SMTP_HOST = env("SMTP_HOST")
SMTP_PORT = int(env("SMTP_PORT", "587"))
SMTP_USER = env("SMTP_USER")
SMTP_PASSWORD = env("SMTP_PASSWORD")
SMTP_FROM = env("SMTP_FROM")

UPLOAD_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024   # videos / audio
MAX_IMAGE_BYTES = 15 * 1024 * 1024    # photos (they are shrunk automatically after upload)


def razorpay_configured():
    return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)
