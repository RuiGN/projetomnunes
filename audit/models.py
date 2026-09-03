"""Immutable, tenant-scoped audit persistence models."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, NoReturn
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.db import models
from django.utils import timezone


class AuditTenantScopeRequiredError(RuntimeError):
    """Raised when audit records are queried without an explicit clinic."""


def _authenticated_digest(payload: bytes) -> str:
    """Authenticate integrity metadata with a key held outside the database."""
    key = getattr(settings, "AUDIT_INTEGRITY_KEY", "")
    if not isinstance(key, str) or len(key) < 32:
        raise ImproperlyConfigured(
            "AUDIT_INTEGRITY_KEY must contain at least 32 characters."
        )
    return hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


class AuditAction(models.TextChoices):
    """Stable taxonomy for sensitive platform operations."""

    LOGIN = "login", "Login"
    CLINIC_SWITCH = "clinic_switch", "Troca de clínica"
    VIEW = "view", "Visualização"
    CREATE = "create", "Criação"
    UPDATE = "update", "Alteração"
    EXPORT = "export", "Exportação"
    CONSENT_ACCEPT = "consent_accept", "Aceite de consentimento"
    CONSENT_REFUSE = "consent_refuse", "Recusa de consentimento"
    CONSENT_REVOKE = "consent_revoke", "Revogação de consentimento"
    PERMISSION_CHANGE = "permission_change", "Alteração de permissão"
    DELETE = "delete", "Exclusão"
    AUDIT_QUERY = "audit_query", "Consulta de auditoria"


class AuditOutcome(models.TextChoices):
    """Stable operation outcomes without copying sensitive response details."""

    SUCCESS = "success", "Sucesso"
    DENIED = "denied", "Negado"
    ERROR = "error", "Erro"


class AuditEventQuerySet(models.QuerySet["AuditEvent"]):
    """Tenant-bound read interface that rejects destructive operations."""

    def for_clinic(self, clinic_id: UUID) -> AuditEventQuerySet:
        """Restrict events to one explicit clinic."""
        return self.filter(clinic_id=clinic_id)

    def update(self, **kwargs: Any) -> NoReturn:
        """Reject bulk mutation of append-only events."""
        raise PermissionDenied("Audit events are append-only.")

    def delete(self) -> NoReturn:
        """Reject bulk deletion of append-only events."""
        raise PermissionDenied("Audit events are append-only.")


class AuditEventManager(models.Manager["AuditEvent"]):
    """Default manager requiring explicit tenant scope."""

    def get_queryset(self) -> NoReturn:
        """Reject global audit enumeration."""
        raise AuditTenantScopeRequiredError(
            "AuditEvent queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> AuditEventQuerySet:
        """Return a tenant-scoped, append-only queryset."""
        return AuditEventQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureAuditEventManager(models.Manager["AuditEvent"]):
    """Unrestricted manager reserved for integrity and append services."""

    def get_queryset(self) -> AuditEventQuerySet:
        return AuditEventQuerySet(self.model, using=self._db)


class AuditEvent(models.Model):
    """Append-only event chained to the previous event in the same clinic."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    sequence = models.PositiveBigIntegerField()
    occurred_at = models.DateTimeField(default=timezone.now, editable=False)
    actor_id = models.UUIDField(blank=True, null=True)
    action = models.CharField(max_length=32, choices=AuditAction)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=255)
    outcome = models.CharField(max_length=16, choices=AuditOutcome)
    request_id = models.UUIDField()
    network_origin_digest = models.CharField(max_length=64, blank=True)
    justification_digest = models.CharField(max_length=64, blank=True)
    previous_hash = models.CharField(max_length=64, blank=True)
    event_hash = models.CharField(max_length=64, unique=True)
    retention_until = models.DateTimeField()

    objects = AuditEventManager()
    infrastructure_objects = InfrastructureAuditEventManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        ordering = ("sequence",)
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "sequence"),
                name="unique_audit_sequence_per_clinic",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "occurred_at"),
                name="audit_clinic_time_idx",
            ),
            models.Index(
                fields=("clinic", "actor_id", "occurred_at"),
                name="audit_clinic_actor_idx",
            ),
            models.Index(
                fields=("clinic", "action", "outcome"),
                name="audit_clinic_action_idx",
            ),
            models.Index(
                fields=("clinic", "resource_type", "resource_id"),
                name="audit_clinic_resource_idx",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Allow only the initial append performed by the audit service."""
        if not self._state.adding:
            raise PermissionDenied("Audit events are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        """Reject instance deletion through common model interfaces."""
        raise PermissionDenied("Audit events are append-only.")

    def integrity_payload(self) -> dict[str, object]:
        """Return the canonical technical fields covered by the event hash."""
        payload: dict[str, object] = {
            "id": str(self.id),
            "clinic_id": str(self.clinic_id),
            "sequence": self.sequence,
            "occurred_at": self.occurred_at.isoformat(),
            "actor_id": str(self.actor_id) if self.actor_id else None,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "outcome": self.outcome,
            "request_id": str(self.request_id),
            "network_origin_digest": self.network_origin_digest,
            "previous_hash": self.previous_hash,
            "retention_until": self.retention_until.isoformat(),
        }
        if self.justification_digest:
            payload["justification_digest"] = self.justification_digest
        return payload

    def expected_hash(self) -> str:
        """Calculate the canonical authenticated integrity digest."""
        serialized = json.dumps(
            self.integrity_payload(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return _authenticated_digest(serialized.encode("utf-8"))

    @classmethod
    def verify_chain(cls, *, clinic_id: UUID) -> bool:
        """Detect missing sequence numbers, broken links and altered fields."""
        expected_sequence = 1
        previous_hash = ""
        checkpoint = AuditCheckpoint.objects.filter(clinic_id=clinic_id).first()
        events = cls.infrastructure_objects.filter(clinic_id=clinic_id).order_by(
            "sequence"
        )
        for event in events.iterator():
            if event.sequence != expected_sequence:
                return False
            if event.previous_hash != previous_hash:
                return False
            if event.event_hash != event.expected_hash():
                return False
            previous_hash = event.event_hash
            expected_sequence += 1
        terminal_sequence = expected_sequence - 1
        if checkpoint is None:
            return terminal_sequence == 0
        return (
            checkpoint.signature == checkpoint.expected_signature()
            and checkpoint.terminal_sequence == terminal_sequence
            and checkpoint.terminal_hash == previous_hash
        )


class AuditCheckpoint(models.Model):
    """Authenticated expected tail for one tenant audit chain."""

    clinic = models.OneToOneField(
        "clinics.Clinic",
        on_delete=models.PROTECT,
        primary_key=True,
        related_name="audit_checkpoint",
    )
    terminal_sequence = models.PositiveBigIntegerField()
    terminal_hash = models.CharField(max_length=64)
    signature = models.CharField(max_length=64)
    updated_at = models.DateTimeField(auto_now=True)

    def expected_signature(self) -> str:
        """Authenticate the expected tail with the independent integrity key."""
        payload = (
            f"{self.clinic_id}:{self.terminal_sequence}:{self.terminal_hash}"
        ).encode()
        return _authenticated_digest(payload)
