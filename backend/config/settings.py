"""Minimal settings: no auth, no admin, no sessions (out of scope, see README).

All database configuration comes from environment variables. For local
convenience, KEY=VALUE lines in backend/.env are loaded if the file exists
(see .env.example). Real environment variables always win.
"""
import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent


def _load_dotenv(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():  # tolerate a BOM (PowerShell 5.1)
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(BASE_DIR / ".env")

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

# SECRET_KEY signs tenant-context tokens, so it must never be a value committed to the repo.
# Dev without one: a random key per process (tenant contexts reset on restart).
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0.")
    SECRET_KEY = secrets.token_urlsafe(50)
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "rest_framework",
    "recon",
]
MIDDLEWARE = ["django.middleware.common.CommonMiddleware"]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "adosx"),
        "USER": os.environ.get("POSTGRES_USER", "adosx"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

REST_FRAMEWORK = {
    # Tenant scoping is the default for every view (see recon/tenancy.py).
    "DEFAULT_AUTHENTICATION_CLASSES": ["recon.tenancy.TenantTokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["recon.tenancy.TenantContextRequired"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "COERCE_DECIMAL_TO_STRING": True,  # money stays exact on the wire
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

# Demo stand-in for login: POST /api/tenant-context/ issues a context for any org.
# Defaults to on only with DEBUG. Turn off anywhere real tenants exist.
ADOSX_DEMO_TENANT_SWITCHING = os.environ.get("ADOSX_DEMO_TENANT_SWITCHING", "1" if DEBUG else "0") == "1"
TENANT_CONTEXT_MAX_AGE = int(os.environ.get("TENANT_CONTEXT_MAX_AGE", 8 * 3600))  # seconds

# Where `manage.py import_data` looks by default.
DATA_DIR = Path(os.environ.get("ADOSX_DATA_DIR", REPO_ROOT / "data"))
