"""Central configuration. Everything is overridable through environment variables or a .env file."""
import os
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent.parent


def _load_dotenv() -> None:
    env = BASE_DIR / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    """Environment value, treating an empty string (e.g. `KEY=` left blank in .env) as unset."""
    # strip: a pasted value often carries a trailing newline or space, which silently breaks URLs, keys and headers
    return (os.getenv(name) or default).strip()


def _flag(name: str, default: bool = False) -> bool:
    return _env(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


DATA_DIR = Path(_env("UDYAM_DATA_DIR", str(PROJECT_ROOT / "YTL_TrackA_Udyam_Digital_Data")))

# ---- mode ----------------------------------------------------------------------------------
# DEMO_MODE turns on helpers that only make sense for showcasing: sample applicants, simulated
# payment decline and a timer that auto-advances orders. Off in production.
DEMO_MODE = _flag("DEMO_MODE")

# Date used for all date based checks (address proof age, ID validity, install dates).
# Production uses the real date. The case README fixes 2026-07-15 for its specimen documents,
# so set UDYAM_TODAY=2026-07-15 when evaluating with those files.
TODAY = date.fromisoformat(_env("UDYAM_TODAY") or date.today().isoformat())
ADDRESS_PROOF_MAX_AGE_DAYS = 90

# ---- database (Supabase Postgres in production, SQLite for quick local runs) ------------------
def _normalise_db_url(url: str) -> str:
    # Supabase hands out postgresql:// or postgres:// URLs; SQLAlchemy needs the driver name.
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _normalise_db_url(_env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'udyam.db'}"))
IS_POSTGRES = DATABASE_URL.startswith("postgresql")
# create_all is for SQLite and tests; Postgres schema is managed by Alembic migrations.
AUTO_CREATE_TABLES = _flag("AUTO_CREATE_TABLES", not IS_POSTGRES)

# ---- document storage ----------------------------------------------------------------------
UPLOAD_DIR = Path(_env("UDYAM_UPLOAD_DIR", str(BASE_DIR / "uploads")))
SUPABASE_URL = _env("SUPABASE_URL").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = _env("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET = _env("SUPABASE_BUCKET", "kyc-documents")
STORAGE_BACKEND = _env("STORAGE_BACKEND") or ("supabase" if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else "local")

# ---- authentication (Clerk) ----------------------------------------------------------------
# CLERK_ISSUER is the "Frontend API URL" from the Clerk dashboard, e.g. https://xxx.clerk.accounts.dev
CLERK_ISSUER = _env("CLERK_ISSUER").rstrip("/")
CLERK_AUTHORIZED_PARTIES = [p.strip() for p in _env("CLERK_AUTHORIZED_PARTIES").split(",") if p.strip()]
AUTH_REQUIRED = bool(CLERK_ISSUER) and not _flag("AUTH_DISABLED")
STAFF_ROLES = {"sales", "ops", "admin"}

# ---- LLM (Gemini free tier) ----------------------------------------------------------------
GEMINI_API_KEY = _env("GEMINI_API_KEY")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-2.5-flash")
LLM_TIMEOUT_S = float(_env("LLM_TIMEOUT_S", "20"))

# ---- payments (Razorpay). Without keys the test-mode stub is used (never in production) ----------
RAZORPAY_KEY_ID = _env("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = _env("RAZORPAY_KEY_SECRET")
RAZORPAY_WEBHOOK_SECRET = _env("RAZORPAY_WEBHOOK_SECRET")

# ---- orders / privacy / web ----------------------------------------------------------------
DEMO_STEP_SECONDS = float(_env("DEMO_STEP_SECONDS", "6"))
KYC_RETENTION_DAYS_REJECTED = int(_env("KYC_RETENTION_DAYS_REJECTED", "30"))
CORS_ORIGINS = _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
