"""Central configuration for JobScout.

Every tunable lives here and is overridable through environment variables so the
same codebase runs locally and in production without edits.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

try:  # optional, but handy in development
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:  # pragma: no cover
    pass


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("JOBSCOUT_DB", DATA_DIR / "jobscout.sqlite3"))
SEED_FILE = DATA_DIR / "employers.json"


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


class Settings:
    # ---- paths ----
    BASE_DIR = BASE_DIR
    DATA_DIR = DATA_DIR
    DB_PATH = DB_PATH
    SEED_FILE = SEED_FILE

    # ---- app ----
    APP_NAME = "JobScout"
    TAGLINE = "Marrakech employer field book"
    CITY = os.getenv("JOBSCOUT_CITY", "Marrakech, Morocco")
    SECRET_KEY = os.getenv("JOBSCOUT_SECRET_KEY") or secrets.token_hex(32)
    DEBUG = _flag("JOBSCOUT_DEBUG", False)
    HOST = os.getenv("JOBSCOUT_HOST", "127.0.0.1")
    PORT = _int("JOBSCOUT_PORT", 8050)

    # Session cookie hardening. Set JOBSCOUT_HTTPS=1 behind TLS.
    SESSION_COOKIE_SECURE = _flag("JOBSCOUT_HTTPS", False)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME_DAYS = _int("JOBSCOUT_SESSION_DAYS", 14)

    # ---- signup gate ----
    # First account created always becomes an admin. Afterwards, open signup can
    # be closed, or restricted to an invite code.
    ALLOW_SIGNUP = _flag("JOBSCOUT_ALLOW_SIGNUP", True)
    SIGNUP_INVITE_CODE = os.getenv("JOBSCOUT_INVITE_CODE", "").strip()

    # ---- scoring weights ----
    W_RATING = float(os.getenv("JOBSCOUT_W_RATING", "0.35"))
    W_REVIEWS = float(os.getenv("JOBSCOUT_W_REVIEWS", "0.25"))
    W_GAP = float(os.getenv("JOBSCOUT_W_GAP", "0.25"))
    W_REACH = float(os.getenv("JOBSCOUT_W_REACH", "0.15"))

    # ---- AI (Google Gemini) ----
    GEMINI_API_KEY = (
        os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    ).strip()
    AI_MODEL = os.getenv("JOBSCOUT_AI_MODEL", "gemini-2.5-pro")
    AI_MAX_TOKENS = _int("JOBSCOUT_AI_MAX_TOKENS", 4000)
    AI_EFFORT = os.getenv("JOBSCOUT_AI_EFFORT", "medium")

    # ---- SMTP ----
    SMTP_HOST = os.getenv("JOBSCOUT_SMTP_HOST", "").strip()
    SMTP_PORT = _int("JOBSCOUT_SMTP_PORT", 587)
    SMTP_USER = os.getenv("JOBSCOUT_SMTP_USER", "").strip()
    SMTP_PASSWORD = os.getenv("JOBSCOUT_SMTP_PASSWORD", "")
    SMTP_STARTTLS = _flag("JOBSCOUT_SMTP_STARTTLS", True)
    SMTP_SSL = _flag("JOBSCOUT_SMTP_SSL", False)
    MAIL_FROM = os.getenv("JOBSCOUT_MAIL_FROM", "").strip()
    MAIL_FROM_NAME = os.getenv("JOBSCOUT_MAIL_FROM_NAME", "JobScout")
    MAIL_REPLY_TO = os.getenv("JOBSCOUT_MAIL_REPLY_TO", "").strip()
    # Nothing leaves the machine while this is on: sends are written to the log
    # table with status "simulated".
    MAIL_DRY_RUN = _flag("JOBSCOUT_MAIL_DRY_RUN", True)
    MAIL_DAILY_CAP = _int("JOBSCOUT_MAIL_DAILY_CAP", 60)

    @classmethod
    def ai_enabled(cls) -> bool:
        return bool(cls.GEMINI_API_KEY)

    @classmethod
    def smtp_configured(cls) -> bool:
        return bool(cls.SMTP_HOST and cls.MAIL_FROM)


settings = Settings()
