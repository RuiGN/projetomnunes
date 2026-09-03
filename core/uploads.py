"""Validation primitives for quarantined private uploads."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.core.signing import TimestampSigner


class MalwareScanStatus(StrEnum):
    """Normalized malware scanning states for private objects."""

    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class PrivateUploadRecord:
    """Persisted server-owned identity and malware state for one upload."""

    id: str
    tenant_id: str
    original_name: str
    media_type: str
    size: int
    quarantine_key: str
    status: MalwareScanStatus = MalwareScanStatus.PENDING
    active_object_key: str | None = None

    @property
    def active_key(self) -> str:
        """Return the promoted key, failing closed before promotion."""
        if self.active_object_key is None:
            raise PermissionDenied("Private upload is not available for download.")
        return self.active_object_key


class PrivateStorage(Protocol):
    """Server-owned private object storage operations."""

    def store_private(self, *, object_key: str, upload: UploadedFile) -> None: ...

    def promote_private(self, *, source_key: str, destination_key: str) -> None: ...

    def isolate(self, *, object_key: str) -> None: ...

    def temporary_download_url(self, *, object_key: str, expires_in: int) -> str: ...


class MalwareScanner(Protocol):
    """Scan an object already held in the quarantine namespace."""

    def scan(self, *, object_key: str) -> MalwareScanStatus: ...


class UploadMetadataRepository(Protocol):
    """Durably store and retrieve upload state by server-issued identity."""

    def save(self, record: PrivateUploadRecord) -> None: ...

    def get(self, upload_id: str) -> PrivateUploadRecord | None: ...


@dataclass(frozen=True, slots=True)
class PrivateDownloadGrant:
    """Short-lived, tenant-bound authorization for one private object."""

    token: str
    salt = "core.private-download.v1"

    @classmethod
    def issue(cls, *, object_key: str, tenant_id: str) -> PrivateDownloadGrant:
        """Sign an opaque object reference together with its owning tenant."""
        if not object_key or not tenant_id:
            raise ValueError("Object key and tenant ID are required.")
        signer = TimestampSigner(salt=cls.salt)
        token = signer.sign_object(
            {"object_key": object_key, "tenant_id": tenant_id},
            compress=True,
        )
        return cls(token=token)

    def resolve(self, *, tenant_id: str, max_age_seconds: int) -> str:
        """Return the object key only for the tenant and validity window."""
        signer = TimestampSigner(salt=self.salt)
        payload = signer.unsign_object(self.token, max_age=max_age_seconds)
        if not isinstance(payload, dict) or payload.get("tenant_id") != tenant_id:
            raise PermissionDenied(
                "Private object grant does not belong to this tenant."
            )
        object_key = payload.get("object_key")
        if not isinstance(object_key, str) or not object_key:
            raise PermissionDenied("Private object grant is invalid.")
        return object_key


@dataclass(frozen=True, slots=True)
class PrivateUploadMetadata:
    """Validated metadata for an object that remains private by default."""

    safe_name: str
    detected_media_type: str
    size: int
    is_public: bool = False

    def can_release(self, scan_status: MalwareScanStatus) -> bool:
        """Allow authorized delivery only after a successful malware scan."""
        return scan_status is MalwareScanStatus.CLEAN


class PrivateUploadService:
    """Own upload identities, quarantine scanning and private promotion."""

    def __init__(
        self,
        *,
        storage: PrivateStorage,
        scanner: MalwareScanner,
        repository: UploadMetadataRepository,
        policy: PrivateUploadPolicy | None = None,
    ) -> None:
        self.storage = storage
        self.scanner = scanner
        self.repository = repository
        self.policy = policy or PrivateUploadPolicy()

    def upload(self, *, tenant_id: str, upload: UploadedFile) -> PrivateUploadRecord:
        """Quarantine one validated upload and fail closed unless it scans clean."""
        if not tenant_id.strip():
            raise ValueError("Tenant ID is required.")
        metadata = self.policy.validate(upload)
        upload_id = uuid4().hex
        quarantine_key = f"{tenant_id}/quarantine/{upload_id}/{metadata.safe_name}"
        record = PrivateUploadRecord(
            id=upload_id,
            tenant_id=tenant_id,
            original_name=metadata.safe_name,
            media_type=metadata.detected_media_type,
            size=metadata.size,
            quarantine_key=quarantine_key,
        )
        self.repository.save(record)
        upload.seek(0)
        self.storage.store_private(object_key=quarantine_key, upload=upload)

        status = self.scanner.scan(object_key=quarantine_key)
        if not isinstance(status, MalwareScanStatus):
            status = MalwareScanStatus.ERROR
        if status is MalwareScanStatus.CLEAN:
            active_key = f"{tenant_id}/private/{upload_id}/{metadata.safe_name}"
            self.storage.promote_private(
                source_key=quarantine_key,
                destination_key=active_key,
            )
            record = replace(
                record,
                status=status,
                active_object_key=active_key,
            )
        else:
            self.storage.isolate(object_key=quarantine_key)
            record = replace(record, status=status)
        self.repository.save(record)
        return record


class PrivateUploadPolicy:
    """Validate size, extension, declaration and magic bytes before quarantine."""

    max_size = 10 * 1024 * 1024
    allowed_types: dict[str, tuple[str, tuple[bytes, ...]]] = {
        ".pdf": ("application/pdf", (b"%PDF-",)),
        ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
        ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
        ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    }

    def validate(self, upload: UploadedFile) -> PrivateUploadMetadata:
        """Return normalized metadata or reject an unsafe upload."""
        name = upload.name or ""
        size = upload.size or 0
        suffix = Path(name).suffix.lower()
        expected = self.allowed_types.get(suffix)
        if expected is None:
            raise ValidationError("Tipo de arquivo não permitido.")
        expected_media_type, signatures = expected
        if upload.content_type != expected_media_type:
            raise ValidationError("O tipo declarado do arquivo é inválido.")
        if size <= 0 or size > self.max_size:
            raise ValidationError("O arquivo está vazio ou excede o limite permitido.")

        position = upload.tell()
        header = upload.read(16)
        upload.seek(position)
        if not any(header.startswith(signature) for signature in signatures):
            raise ValidationError(
                "O conteúdo do arquivo não corresponde ao tipo informado."
            )

        safe_name = f"{uuid4().hex}{suffix}"
        return PrivateUploadMetadata(
            safe_name=safe_name,
            detected_media_type=expected_media_type,
            size=size,
        )


def require_clean_malware_scan(upload: UploadedFile) -> None:
    """Fail closed unless the configured scanner clears a temporary upload."""
    command = getattr(settings, "PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND", ())
    if (
        not isinstance(command, (tuple, list))
        or not command
        or not all(isinstance(part, str) and part for part in command)
    ):
        raise ValidationError("A varredura de segurança do arquivo está indisponível.")
    original_position = upload.tell()
    try:
        upload.seek(0)
        with NamedTemporaryFile(suffix=Path(upload.name or "").suffix) as temporary:
            for chunk in upload.chunks():
                temporary.write(chunk)
            temporary.flush()
            completed = subprocess.run(
                [*command, temporary.name],
                capture_output=True,
                check=False,
                timeout=30,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValidationError(
            "A varredura de segurança do arquivo está indisponível."
        ) from exc
    finally:
        upload.seek(original_position)
    if completed.returncode != 0:
        raise ValidationError("O arquivo não foi aprovado na varredura de segurança.")
