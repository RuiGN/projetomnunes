"""Security configuration and private-upload acceptance tests."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.core.signing import SignatureExpired
from django.http import HttpResponse
from django.test import Client

from core.security import SecurityHeadersMiddleware
from core.uploads import (
    MalwareScanStatus,
    PrivateDownloadGrant,
    PrivateUploadPolicy,
    PrivateUploadRecord,
    PrivateUploadService,
)
from scripts.check_secrets import find_secrets

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MemoryUploadRepository:
    """Persist upload state for service-level acceptance tests."""

    def __init__(self) -> None:
        self.records: dict[str, PrivateUploadRecord] = {}

    def save(self, record: PrivateUploadRecord) -> None:
        self.records[record.id] = record

    def get(self, upload_id: str) -> PrivateUploadRecord | None:
        return self.records.get(upload_id)


class RecordingPrivateStorage:
    """Record private storage operations without exposing caller-owned keys."""

    def __init__(self) -> None:
        self.stored: list[str] = []
        self.promoted: list[tuple[str, str]] = []
        self.isolated: list[str] = []

    def store_private(self, *, object_key: str, upload: UploadedFile) -> None:
        assert upload.read()
        self.stored.append(object_key)

    def promote_private(self, *, source_key: str, destination_key: str) -> None:
        self.promoted.append((source_key, destination_key))

    def isolate(self, *, object_key: str) -> None:
        self.isolated.append(object_key)

    def temporary_download_url(self, *, object_key: str, expires_in: int) -> str:
        return f"https://storage.test/{object_key}?expires={expires_in}"


class FixedScanner:
    """Return one normalized scanner result and record the scanned key."""

    def __init__(self, status: MalwareScanStatus) -> None:
        self.status = status
        self.scanned: list[str] = []

    def scan(self, *, object_key: str) -> MalwareScanStatus:
        self.scanned.append(object_key)
        return self.status


def test_application_responses_have_restrictive_security_headers(
    client: Client,
) -> None:
    """Security headers protect every response without relying on a reverse proxy."""
    response = client.get("/")

    assert response.headers["Content-Security-Policy"] == (
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; "
        "form-action 'self'; object-src 'none'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'"
    )
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert (
        response.headers["Permissions-Policy"]
        == "camera=(), microphone=(), geolocation=()"
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_security_middleware_overrides_permissive_downstream_headers() -> None:
    """A view cannot weaken the application-owned browser security policy."""

    def permissive_response(_request: object) -> HttpResponse:
        response = HttpResponse()
        response["Content-Security-Policy"] = "default-src * 'unsafe-eval'"
        response["Referrer-Policy"] = "unsafe-url"
        response["X-Frame-Options"] = "SAMEORIGIN"
        return response

    response = SecurityHeadersMiddleware(permissive_response)(object())  # type: ignore[arg-type]

    assert response["Content-Security-Policy"].startswith("default-src 'self'")
    assert response["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response["X-Frame-Options"] == "DENY"


def test_production_enforces_secure_session_and_csrf_configuration() -> None:
    """Production HTTPS, cookie and proxy settings fail closed."""
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "DJANGO_SECRET_KEY": "test-production-secret-that-is-long-enough",
            "AUDIT_INTEGRITY_KEY": (
                "test-audit-integrity-key-with-32-characters-minimum"
            ),
            "MFA_ENCRYPTION_KEY": "test-mfa-encryption-key-with-32-characters",
            "DJANGO_ALLOWED_HOSTS": "example.test",
            "DB_NAME": "test",
            "DB_USER": "test",
            "DB_PASSWORD": "test",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "5432",
            "DB_SSLROOTCERT": "/run/secrets/postgresql-ca.pem",
            "CACHE_URL": "redis://cache.internal:6379/1",
            "DJANGO_SECURE_HSTS_SECONDS": "0",
        }
    )
    expression = (
        "from django.conf import settings; "
        "print(settings.SECURE_SSL_REDIRECT, settings.SESSION_COOKIE_SECURE, "
        "settings.SESSION_COOKIE_HTTPONLY, settings.SESSION_COOKIE_SAMESITE, "
        "settings.CSRF_COOKIE_SECURE, settings.CSRF_COOKIE_SAMESITE, "
        "settings.SECURE_PROXY_SSL_HEADER, settings.SECURE_HSTS_SECONDS, "
        "settings.DATABASES['default']['OPTIONS'], "
        "settings.SENSITIVE_REAUTH_RATE_LIMIT_ATTEMPTS, "
        "settings.SENSITIVE_REAUTH_RATE_LIMIT_WINDOW_SECONDS)"
    )
    result = subprocess.run(
        [sys.executable, "-c", expression],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.stdout.strip() == (
        "True True True Lax True Lax ('HTTP_X_FORWARDED_PROTO', 'https') "
        "31536000 {'sslmode': 'verify-full', "
        "'sslrootcert': '/run/secrets/postgresql-ca.pem'} 5 300"
    )


def test_production_requires_a_shared_cache_for_authentication_limits() -> None:
    """Multi-process production cannot silently use process-local rate limits."""
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "DJANGO_SECRET_KEY": "test-production-secret-that-is-long-enough",
            "AUDIT_INTEGRITY_KEY": (
                "test-audit-integrity-key-with-32-characters-minimum"
            ),
            "MFA_ENCRYPTION_KEY": "test-mfa-encryption-key-with-32-characters",
            "DJANGO_ALLOWED_HOSTS": "example.test",
            "DB_NAME": "test",
            "DB_USER": "test",
            "DB_PASSWORD": "test",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "5432",
            "DB_SSLROOTCERT": "/run/secrets/postgresql-ca.pem",
        }
    )
    environment.pop("CACHE_URL", None)

    missing = subprocess.run(
        [sys.executable, "-c", "import config.settings.production"],
        capture_output=True,
        check=False,
        text=True,
        env=environment,
    )
    assert missing.returncode != 0
    assert "CACHE_URL" in missing.stderr

    environment["CACHE_URL"] = "redis://cache.internal:6379/1"
    configured = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from django.conf import settings; "
                "print(settings.CACHES['default']['BACKEND'], "
                "settings.CACHES['default']['LOCATION'])"
            ),
        ],
        capture_output=True,
        check=True,
        text=True,
        env=environment,
    )
    assert configured.stdout.strip() == (
        "django.core.cache.backends.redis.RedisCache redis://cache.internal:6379/1"
    )


def test_private_upload_policy_accepts_allowlisted_pdf_after_clean_scan() -> None:
    """An allowlisted file is releasable only after a clean malware result."""
    upload = SimpleUploadedFile(
        "relatorio.pdf",
        b"%PDF-1.7\nsynthetic test",
        content_type="application/pdf",
    )

    metadata = PrivateUploadPolicy().validate(upload)

    assert metadata.safe_name.endswith(".pdf")
    assert metadata.detected_media_type == "application/pdf"
    assert metadata.is_public is False
    assert metadata.can_release(MalwareScanStatus.PENDING) is False
    assert metadata.can_release(MalwareScanStatus.CLEAN) is True


def test_upload_service_owns_quarantine_key_and_promotes_only_clean_files() -> None:
    """The service persists pending state, scans quarantine and promotes clean data."""
    repository = MemoryUploadRepository()
    storage = RecordingPrivateStorage()
    scanner = FixedScanner(MalwareScanStatus.CLEAN)
    service = PrivateUploadService(
        storage=storage,
        scanner=scanner,
        repository=repository,
    )
    upload = SimpleUploadedFile(
        "relatorio.pdf",
        b"%PDF-1.7\nservice test",
        content_type="application/pdf",
    )

    record = service.upload(tenant_id="clinic-a", upload=upload)

    assert record.status is MalwareScanStatus.CLEAN
    assert record.quarantine_key.startswith("clinic-a/quarantine/")
    assert record.active_key.startswith("clinic-a/private/")
    assert storage.stored == [record.quarantine_key]
    assert scanner.scanned == [record.quarantine_key]
    assert storage.promoted == [(record.quarantine_key, record.active_key)]
    assert repository.get(record.id) == record


@pytest.mark.parametrize(
    "upload",
    [
        SimpleUploadedFile(
            "script.pdf", b"#!/bin/sh\nexit 0", content_type="application/pdf"
        ),
        SimpleUploadedFile(
            "image.svg", b"<svg onload='alert(1)'>", content_type="image/svg+xml"
        ),
        SimpleUploadedFile(
            "double.pdf.exe", b"MZ", content_type="application/octet-stream"
        ),
    ],
)
def test_private_upload_policy_rejects_mismatched_or_executable_content(
    upload: SimpleUploadedFile,
) -> None:
    """Extension, declared type and magic bytes cannot bypass the allowlist."""
    with pytest.raises(ValidationError):
        PrivateUploadPolicy().validate(upload)


def test_private_download_grant_is_tenant_bound_and_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Signed private-object grants expire and cannot cross tenant boundaries."""
    monkeypatch.setattr("django.core.signing.time.time", lambda: 1_000.0)
    grant = PrivateDownloadGrant.issue(
        object_key="private/clinic-a/report.pdf",
        tenant_id="clinic-a",
    )

    assert grant.resolve(tenant_id="clinic-a", max_age_seconds=300) == (
        "private/clinic-a/report.pdf"
    )
    with pytest.raises(PermissionDenied):
        grant.resolve(tenant_id="clinic-b", max_age_seconds=300)

    monkeypatch.setattr("django.core.signing.time.time", lambda: 1_301.0)
    with pytest.raises(SignatureExpired):
        grant.resolve(tenant_id="clinic-a", max_age_seconds=300)


def test_ci_blocks_committed_secrets_with_repository_owned_scanner() -> None:
    """The quality pipeline scans tracked content before verification completes."""
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "quality.yml").read_text(
        encoding="utf-8"
    )
    scanner = PROJECT_ROOT / "scripts" / "check_secrets.py"

    assert "Secret scan" in workflow
    assert "python scripts/check_secrets.py" in workflow
    assert scanner.is_file()


def test_secret_scanner_detects_generic_high_entropy_credentials(
    tmp_path: Path,
) -> None:
    """Generic password and API-key assignments cannot bypass vendor patterns."""
    source = tmp_path / "settings.py"
    synthetic_value = "Ab9!xQ2@" + "Lm7#Vr4$" + "Np8%Zt6&"
    source.write_text(
        f'database_password = "{synthetic_value}"\n',
        encoding="utf-8",
    )

    assert "generic credential" in find_secrets(source)


def test_security_operations_document_rotation_encryption_and_private_storage() -> None:
    """Operational controls remain explicit and versioned with the code."""
    document = (PROJECT_ROOT / "docs" / "security" / "controls.md").read_text(
        encoding="utf-8"
    )

    for term in (
        "Secret rotation",
        "Least privilege",
        "Private object storage",
        "Database encryption",
        "Backup encryption",
        "Field-level encryption",
        "Independent key management",
        "Malware quarantine",
    ):
        assert term in document
