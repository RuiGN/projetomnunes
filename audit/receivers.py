"""Audit side effects subscribed to public domain events."""

from uuid import UUID

from django.dispatch import receiver

from accounts.events import account_audit_required
from clinics.events import (
    clinic_configuration_updated,
    professional_membership_updated,
    whitelabel_audit_required,
)
from journal.events import (
    daily_checkin_submitted,
    daily_checkin_updated,
    journal_entry_created,
    journal_entry_updated,
    journal_entry_visibility_changed,
)
from people.events import (
    care_relationship_changed,
    patient_profile_updated,
    patient_record_accessed,
    professional_credential_audit_required,
    professional_profile_updated,
)

from .models import AuditAction, AuditOutcome
from .services import record_audit_event


@receiver(account_audit_required, dispatch_uid="audit.account_audit_required.v1")
def audit_account_change(
    sender: object,
    *,
    clinic_id: UUID,
    actor_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: str,
    request_id: UUID,
    network_origin: str | None,
    justification: str | None = None,
    **kwargs: object,
) -> None:
    """Append minimized audit data published by the accounts domain."""
    del sender, kwargs
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=AuditOutcome.SUCCESS,
        request_id=request_id,
        network_origin=network_origin,
        justification=justification,
    )


@receiver(
    clinic_configuration_updated,
    dispatch_uid="audit.clinic_configuration_updated.v1",
)
def audit_clinic_configuration_update(
    sender: object,
    *,
    clinic_id: UUID,
    actor_id: UUID,
    resource_type: str,
    resource_id: str,
    request_id: UUID,
    **kwargs: object,
) -> None:
    """Append one minimized event for a successful clinic configuration change."""
    del sender, kwargs
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=AuditAction.UPDATE,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=AuditOutcome.SUCCESS,
        request_id=request_id,
        network_origin=None,
    )


@receiver(
    professional_profile_updated, dispatch_uid="audit.professional_profile_updated.v1"
)
def audit_professional_profile_update(
    sender: object,
    *,
    clinic_id: UUID,
    actor_id: UUID,
    resource_id: str,
    request_id: UUID,
    **kwargs: object,
) -> None:
    """Append a minimized audit event for one professional profile update."""
    del sender, kwargs
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=AuditAction.UPDATE,
        resource_type="professional_profile",
        resource_id=resource_id,
        outcome=AuditOutcome.SUCCESS,
        request_id=request_id,
        network_origin=None,
    )


@receiver(
    professional_membership_updated,
    dispatch_uid="audit.professional_membership_updated.v1",
)
def audit_professional_membership_update(
    sender: object,
    *,
    clinic_id: UUID,
    actor_id: UUID,
    resource_id: str,
    request_id: UUID,
    **kwargs: object,
) -> None:
    """Append a minimized permission event for a professional membership update."""
    del sender, kwargs
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=AuditAction.PERMISSION_CHANGE,
        resource_type="clinic_membership",
        resource_id=resource_id,
        outcome=AuditOutcome.SUCCESS,
        request_id=request_id,
        network_origin=None,
    )


@receiver(whitelabel_audit_required, dispatch_uid="audit.whitelabel_audit_required.v1")
def audit_whitelabel_audit_required(
    sender: object,
    *,
    clinic_id: UUID,
    actor_id: UUID | None,
    action: AuditAction | str,
    resource_type: str,
    resource_id: str,
    request_id: UUID,
    network_origin: str | None = None,
    justification: str | None = None,
    **kwargs: object,
) -> None:
    """Append a minimized audit event for white-label lifecycle actions."""
    del sender, kwargs
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=AuditOutcome.SUCCESS,
        request_id=request_id,
        network_origin=network_origin,
        justification=justification,
    )


@receiver(
    professional_credential_audit_required,
    dispatch_uid="audit.professional_credential_audit_required.v1",
)
def audit_professional_credential_change(
    sender: object,
    *,
    clinic_id: UUID,
    actor_id: UUID | None,
    action: AuditAction | str,
    resource_type: str,
    resource_id: str,
    request_id: UUID,
    network_origin: str | None = None,
    **kwargs: object,
) -> None:
    """Append a minimized audit event for credential governance actions."""
    del sender, kwargs
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=AuditOutcome.SUCCESS,
        request_id=request_id,
        network_origin=network_origin,
    )


@receiver(patient_profile_updated, dispatch_uid="audit.patient_profile_updated.v1")
def audit_patient_profile_update(
    sender: object,
    *,
    clinic_id: UUID,
    actor_id: UUID,
    resource_id: str,
    request_id: UUID,
    **kwargs: object,
) -> None:
    """Append a minimized audit event for a patient profile change."""
    del sender, kwargs
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=AuditAction.UPDATE,
        resource_type="patient_profile",
        resource_id=resource_id,
        outcome=AuditOutcome.SUCCESS,
        request_id=request_id,
        network_origin=None,
    )


@receiver(care_relationship_changed, dispatch_uid="audit.care_relationship_changed.v1")
def audit_care_relationship_change(
    sender: object,
    *,
    clinic_id: UUID,
    actor_id: UUID,
    resource_id: str,
    request_id: UUID,
    **kwargs: object,
) -> None:
    """Append a minimized audit event for an explicit care-link change."""
    del sender, kwargs
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=AuditAction.PERMISSION_CHANGE,
        resource_type="care_relationship",
        resource_id=resource_id,
        outcome=AuditOutcome.SUCCESS,
        request_id=request_id,
        network_origin=None,
    )


@receiver(patient_record_accessed, dispatch_uid="audit.patient_record_accessed.v1")
def audit_patient_record_access(
    sender: object,
    *,
    clinic_id: UUID,
    actor_id: UUID,
    resource_id: str,
    request_id: UUID,
    **kwargs: object,
) -> None:
    """Append a minimized read event for one authorized patient record view."""
    del sender, kwargs
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=AuditAction.VIEW,
        resource_type="patient_profile",
        resource_id=resource_id,
        outcome=AuditOutcome.SUCCESS,
        request_id=request_id,
        network_origin=None,
    )


def _record_journal_event(
    *,
    clinic_id: UUID,
    actor_id: UUID,
    resource_id: str,
    request_id: UUID,
    action: AuditAction,
) -> None:
    """Append a minimized journal event without clinical content."""
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=action,
        resource_type="journal_entry",
        resource_id=resource_id,
        outcome=AuditOutcome.SUCCESS,
        request_id=request_id,
        network_origin=None,
    )


@receiver(journal_entry_created, dispatch_uid="audit.journal_entry_created.v1")
def audit_journal_entry_created(
    sender: object,
    *,
    clinic_id: UUID,
    actor_id: UUID,
    resource_id: str,
    request_id: UUID,
    **kwargs: object,
) -> None:
    """Append a minimized create event for one diary record."""
    del sender, kwargs
    _record_journal_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        resource_id=resource_id,
        request_id=request_id,
        action=AuditAction.CREATE,
    )


@receiver(journal_entry_updated, dispatch_uid="audit.journal_entry_updated.v1")
def audit_journal_entry_updated(
    sender: object,
    *,
    clinic_id: UUID,
    actor_id: UUID,
    resource_id: str,
    request_id: UUID,
    **kwargs: object,
) -> None:
    """Append a minimized update event for one diary record."""
    del sender, kwargs
    _record_journal_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        resource_id=resource_id,
        request_id=request_id,
        action=AuditAction.UPDATE,
    )


@receiver(
    journal_entry_visibility_changed,
    dispatch_uid="audit.journal_entry_visibility_changed.v1",
)
def audit_journal_entry_visibility_changed(
    sender: object,
    *,
    clinic_id: UUID,
    actor_id: UUID,
    resource_id: str,
    request_id: UUID,
    **kwargs: object,
) -> None:
    """Append a minimized privacy-transition event for one diary record."""
    del sender, kwargs
    _record_journal_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        resource_id=resource_id,
        request_id=request_id,
        action=AuditAction.UPDATE,
    )


def _record_checkin_event(
    *,
    clinic_id: UUID,
    actor_id: UUID,
    resource_id: str,
    request_id: UUID,
    action: AuditAction,
) -> None:
    """Append a minimized check-in event without clinical content."""
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=action,
        resource_type="daily_checkin",
        resource_id=resource_id,
        outcome=AuditOutcome.SUCCESS,
        request_id=request_id,
        network_origin=None,
    )


@receiver(daily_checkin_submitted, dispatch_uid="audit.daily_checkin_submitted.v1")
def audit_daily_checkin_submitted(
    sender: object,
    *,
    clinic_id: UUID,
    actor_id: UUID,
    resource_id: str,
    request_id: UUID,
    **kwargs: object,
) -> None:
    """Append a minimized submission event for one daily check-in."""
    del sender, kwargs
    _record_checkin_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        resource_id=resource_id,
        request_id=request_id,
        action=AuditAction.CREATE,
    )


@receiver(daily_checkin_updated, dispatch_uid="audit.daily_checkin_updated.v1")
def audit_daily_checkin_updated(
    sender: object,
    *,
    clinic_id: UUID,
    actor_id: UUID,
    resource_id: str,
    request_id: UUID,
    **kwargs: object,
) -> None:
    """Append a minimized update event for one daily check-in."""
    del sender, kwargs
    _record_checkin_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        resource_id=resource_id,
        request_id=request_id,
        action=AuditAction.UPDATE,
    )
