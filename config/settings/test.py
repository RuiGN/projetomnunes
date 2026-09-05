"""Hermetic settings for automated tests."""

import os
from typing import Any

from .base import (  # noqa: F401
    ACCOUNT_SESSION_ABSOLUTE_SECONDS,
    ACCOUNT_SESSION_IDLE_SECONDS,
    ASGI_APPLICATION,
    AUDIT_RETENTION_DAYS,
    AUTH_PASSWORD_VALIDATORS,
    AUTH_USER_MODEL,
    BASE_DIR,
    CACHES,
    CONSENT_REVOCATION_DESTINATIONS,
    CONTENT_SECURITY_POLICY,
    DEFAULT_AUTO_FIELD,
    DEFAULT_FROM_EMAIL,
    INSTALLED_APPS,
    LANGUAGE_CODE,
    LOCALE_PATHS,
    LOGGING,
    LOGIN_RATE_LIMIT_ATTEMPTS,
    LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    LOGIN_URL,
    MEDIA_ROOT,
    MEDIA_URL,
    MFA_ENCRYPTION_KEY,
    MFA_ENFORCEMENT_ENABLED,
    MFA_RATE_LIMIT_ATTEMPTS,
    MFA_RATE_LIMIT_WINDOW_SECONDS,
    MFA_TOTP_ISSUER,
    MIDDLEWARE,
    PASSWORD_RECOVERY_RATE_LIMIT_ATTEMPTS,
    PASSWORD_RECOVERY_RATE_LIMIT_WINDOW_SECONDS,
    PASSWORD_RESET_TIMEOUT,
    PERMISSIONS_POLICY,
    PRIVACY_EXPORT_TTL_SECONDS,
    PRIVACY_LIFECYCLE_DESTINATIONS,
    PRIVACY_REAUTH_MAX_AGE_SECONDS,
    PRIVACY_REQUEST_DUE_DAYS,
    PRIVATE_MEDIA_ROOT,
    PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND,
    REFERRER_POLICY,
    ROOT_URLCONF,
    SENSITIVE_REAUTH_RATE_LIMIT_ATTEMPTS,
    SENSITIVE_REAUTH_RATE_LIMIT_WINDOW_SECONDS,
    STATIC_ROOT,
    STATIC_URL,
    STATICFILES_DIRS,
    TEMPLATES,
    TIME_ZONE,
    USE_I18N,
    USE_TZ,
    WSGI_APPLICATION,
    postgres_database_from_environment,
)

SECRET_KEY = "test-only-not-a-secret"
AUDIT_INTEGRITY_KEY = "test-audit-integrity-key-with-32-characters-minimum"
DEBUG = False
ALLOWED_HOSTS = ["testserver"]
DATABASES: dict[str, Any]
if os.environ.get("TEST_DATABASE") == "postgresql":
    DATABASES = {"default": postgres_database_from_environment()}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("SQLITE_NAME", ":memory:"),
        }
    }
MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
# Test clients commonly use force_login(), which bypasses the real login service that
# registers managed sessions. Security tests override this to False explicitly.
ACCOUNT_SESSION_ALLOW_UNKNOWN = True
