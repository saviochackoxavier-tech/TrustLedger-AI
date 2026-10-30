"""
TrustLedger AI — Django Settings
================================
SQLite (zero config) + env-driven secrets. python-dotenv loads `.env`
from the project root before any module reads os.getenv().

Security contract:
- Every credential (PAYPAL_CLIENT_ID/SECRET, GEMINI_API_KEY, SECRET_KEY)
  is read from the environment ONLY — zero hardcoded fallbacks.
- DEBUG=0 requires a real SECRET_KEY and enables production hardening.
"""

import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# --- Security -------------------------------------------------------------
DEBUG = os.getenv("DEBUG", "1") == "1"

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        # Ephemeral per-process dev key — never hardcoded, never persisted.
        SECRET_KEY = secrets.token_urlsafe(64)
    else:
        raise ImproperlyConfigured(
            "SECRET_KEY must be set via .env when DEBUG=0. "
            "API credentials must never be hardcoded."
        )

ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CSRF_TRUSTED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000"
    ).split(",")
    if o.strip()
]

# --- Applications ----------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "django.contrib.messages",
    "trustledger",  # core escrow app (admin/auth not needed for demo)
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",  # global CSRF on all POSTs
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,  # picks up trustledger/templates/
        "OPTIONS": {"context_processors": [
            "django.template.context_processors.request",
            "django.contrib.messages.context_processors.messages",
        ]},
    },
]

# --- Database: SQLite, zero configuration ----------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# --- i18n / static ----------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# No session backend is installed (stateless demo), so flash messages are
# carried in a signed cookie instead of the session store.
MESSAGE_STORAGE = "django.contrib.messages.storage.cookie.CookieStorage"

# Dispute modal + dashboard JS use POST via fetch(): JS reads the csrftoken
# cookie for the X-CSRFToken header; CsrfViewMiddleware verifies every POST.
CSRF_COOKIE_HTTPONLY = False

# --- Production hardening (enabled only when DEBUG=0) -----------------------
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
