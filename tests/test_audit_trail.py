"""Immutable, tenant-scoped audit trail acceptance tests."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.utils import timezone

from audit.models import AuditAction, AuditEvent, AuditOutcome
from audit.services import export_audit_events, query_audit_events, record_audit_event
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_audit_taxonomy_covers_sensitive_operations() -> None:
    """Stable technical actions cover every MVP-sensitive operation category."""
    assert set(AuditAction.values) == {
        "login",
        "clinic_switch",
        "view",
        "create",
        "update",
        "export",
        "consent_accept",
        "consent_refuse",
        "consent_revoke",
        "permission_change",
        "delete",
        "audit_query",
    }
    assert set(AuditOutcome.values) == {"success", "denied", "error"}


def test_recorded_event_is_minimized_tenant_scoped_and_chain_verified() -> None:
    """Audit writes preserve required context without accepting clinical payloads."""
    clinic = ClinicFactory.create()
    actor = UserFactory.create()
    request_id = uuid4()

    first = record_audit_event(
        clinic_id=clinic.id,
        actor_id=actor.id,
        action=AuditAction.VIEW,
        resource_type="patient_profile",
        resource_id="synthetic-patient-1",
        outcome=AuditOutcome.SUCCESS,
        request_id=request_id,
        network_origin="203.0.113.42",
    )
    second = record_audit_event(
        clinic_id=clinic.id,
        actor_id=actor.id,
        action=AuditAction.UPDATE,
        resource_type="patient_profile",
        resource_id="synthetic-patient-1",
        outcome=AuditOutcome.DENIED,
        request_id=request_id,
        network_origin="203.0.113.42",
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert first.network_origin_digest != "203.0.113.42"
    assert first.retention_until >= first.occurred_at + timedelta(days=2189)
    assert second.previous_hash == first.event_hash
    assert AuditEvent.verify_chain(clinic_id=clinic.id) is True


def test_blank_justification_preserves_legacy_audit_hash_schema() -> None:
    """Adding optional justification must not invalidate pre-migration chains."""
    clinic = ClinicFactory.create()
    event = record_audit_event(
        clinic_id=clinic.id,
        actor_id=None,
        action=AuditAction.VIEW,
        resource_type="patient_profile",
        resource_id="legacy-event",
        outcome=AuditOutcome.SUCCESS,
        request_id=uuid4(),
        network_origin=None,
    )
    legacy_payload = event.integrity_payload()
    legacy_payload.pop("justification_digest", None)
    serialized = json.dumps(
        legacy_payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    legacy_hash = hmac.new(
        settings.AUDIT_INTEGRITY_KEY.encode("utf-8"),
        serialized,
        hashlib.sha256,
    ).hexdigest()

    assert event.expected_hash() == legacy_hash


def test_chain_verification_detects_out_of_band_tampering() -> None:
    """Integrity verification detects changes that bypass common model interfaces."""
    clinic = ClinicFactory.create()
    first = record_audit_event(
        clinic_id=clinic.id,
        actor_id=None,
        action=AuditAction.VIEW,
        resource_type="patient_profile",
        resource_id="patient-1",
        outcome=AuditOutcome.SUCCESS,
        request_id=uuid4(),
        network_origin=None,
    )
    second = record_audit_event(
        clinic_id=clinic.id,
        actor_id=None,
        action=AuditAction.UPDATE,
        resource_type="patient_profile",
        resource_id="patient-1",
        outcome=AuditOutcome.SUCCESS,
        request_id=uuid4(),
        network_origin=None,
    )

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE audit_auditevent SET resource_id = %s WHERE id = %s",
            ["tampered", first.id.hex],
        )
    assert AuditEvent.verify_chain(clinic_id=clinic.id) is False

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE audit_auditevent SET resource_id = %s WHERE id = %s",
            ["patient-1", first.id.hex],
        )
        cursor.execute("DELETE FROM audit_auditevent WHERE id = %s", [second.id.hex])
    assert AuditEvent.verify_chain(clinic_id=clinic.id) is False


def test_common_model_interfaces_cannot_update_or_delete_audit_events() -> None:
    """Saved events are append-only through instances and tenant querysets."""
    clinic = ClinicFactory.create()
    event = record_audit_event(
        clinic_id=clinic.id,
        actor_id=None,
        action=AuditAction.LOGIN,
        resource_type="session",
        resource_id="synthetic-session",
        outcome=AuditOutcome.SUCCESS,
        request_id=uuid4(),
        network_origin=None,
    )

    event.outcome = AuditOutcome.ERROR
    with pytest.raises(PermissionDenied):
        event.save()
    with pytest.raises(PermissionDenied):
        event.delete()
    with pytest.raises(PermissionDenied):
        AuditEvent.objects.for_clinic(clinic.id).update(outcome=AuditOutcome.ERROR)
    with pytest.raises(PermissionDenied):
        AuditEvent.objects.for_clinic(clinic.id).delete()


def test_query_is_authorized_filtered_tenant_scoped_and_self_audited() -> None:
    """Only clinic administrators query audit data, and their query is recorded."""
    clinic = ClinicFactory.create()
    other_clinic = ClinicFactory.create()
    admin = UserFactory.create()
    outsider = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=admin,
        role="clinic_admin",
    )
    target = record_audit_event(
        clinic_id=clinic.id,
        actor_id=admin.id,
        action=AuditAction.PERMISSION_CHANGE,
        resource_type="clinic_membership",
        resource_id="membership-1",
        outcome=AuditOutcome.SUCCESS,
        request_id=uuid4(),
        network_origin=None,
    )
    record_audit_event(
        clinic_id=other_clinic.id,
        actor_id=None,
        action=AuditAction.PERMISSION_CHANGE,
        resource_type="clinic_membership",
        resource_id="membership-2",
        outcome=AuditOutcome.SUCCESS,
        request_id=uuid4(),
        network_origin=None,
    )

    with pytest.raises(PermissionDenied):
        query_audit_events(clinic_id=clinic.id, requester=outsider)
    with pytest.raises(PermissionDenied):
        query_audit_events(clinic_id=uuid4(), requester=outsider)

    result = query_audit_events(
        clinic_id=clinic.id,
        requester=admin,
        actor_id=admin.id,
        action=AuditAction.PERMISSION_CHANGE,
        resource_type="clinic_membership",
        resource_id="membership-1",
        outcome=AuditOutcome.SUCCESS,
        occurred_from=timezone.now() - timedelta(minutes=5),
        occurred_to=timezone.now() + timedelta(minutes=5),
    )

    assert list(result) == [target]
    audit_rows = list(
        AuditEvent.objects.for_clinic(clinic.id)
        .order_by("sequence")
        .values_list("action", "outcome")
    )
    assert audit_rows == [
        (AuditAction.PERMISSION_CHANGE, AuditOutcome.SUCCESS),
        (AuditAction.AUDIT_QUERY, AuditOutcome.DENIED),
        (AuditAction.AUDIT_QUERY, AuditOutcome.SUCCESS),
    ]


def test_inactive_actor_or_clinic_cannot_query_audit() -> None:
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=admin,
        role="clinic_admin",
    )

    admin.is_active = False
    admin.save(update_fields=("is_active",))
    with pytest.raises(PermissionDenied):
        query_audit_events(clinic_id=clinic.pk, requester=admin)

    admin.is_active = True
    admin.save(update_fields=("is_active",))
    clinic.is_active = False
    clinic.save(update_fields=("is_active", "updated_at"))
    with pytest.raises(PermissionDenied):
        query_audit_events(clinic_id=clinic.pk, requester=admin)


def test_controlled_export_is_minimized_and_audited() -> None:
    """CSV export contains technical fields only and emits its own audit event."""
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=admin,
        role="clinic_admin",
    )
    record_audit_event(
        clinic_id=clinic.id,
        actor_id=admin.id,
        action=AuditAction.CONSENT_REVOKE,
        resource_type="consent",
        resource_id="consent-1",
        outcome=AuditOutcome.SUCCESS,
        request_id=uuid4(),
        network_origin=None,
    )

    exported = export_audit_events(clinic_id=clinic.id, requester=admin)

    assert "event_hash" in exported.splitlines()[0]
    assert "network_origin_digest" in exported.splitlines()[0]
    assert "clinical_content" not in exported
    assert (
        AuditEvent.objects.for_clinic(clinic.id)
        .filter(action=AuditAction.EXPORT)
        .exists()
    )
