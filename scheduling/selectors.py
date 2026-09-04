"""Read selectors for the scheduling domain."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.selectors import Selector as Selector
from people.selectors import linked_patients_for_therapist, patient_profile_for_user

from .models import (
    Appointment,
    AppointmentStatus,
    Conversation,
    ConversationParticipant,
    Message,
    ReminderPreference,
    Service,
    WaitlistEntry,
    WaitlistStatus,
)

__all__ = [
    "AppointmentStatus",
    "Selector",
    "Service",
    "WaitlistStatus",
    "active_services_for_clinic",
    "appointment_for_finance",
    "appointment_for_integrations",
    "appointments_visible_to",
    "conversations_for_actor",
    "messages_for_conversation",
    "reminder_preferences_for_patient",
    "waitlist_entries_visible_to",
]


def active_services_for_clinic(*, clinic_id: UUID) -> list[Service]:
    """Return active bookable services for one clinic, ordered by name."""
    return list(
        Service.objects.for_clinic(clinic_id).filter(is_active=True).order_by("name")
    )


def appointment_for_finance(
    *, clinic_id: UUID, appointment_id: UUID
) -> Appointment | None:
    """Return one appointment for finance charge generation, tenant-scoped."""
    return Appointment.objects.for_clinic(clinic_id).filter(pk=appointment_id).first()


def appointment_for_integrations(
    *, clinic_id: UUID, appointment_id: UUID
) -> Appointment | None:
    """Return one appointment for external integrations, tenant-scoped."""
    return Appointment.objects.for_clinic(clinic_id).filter(pk=appointment_id).first()


def appointments_visible_to(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    status: str = "",
    on_date: date | None = None,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
) -> list[Appointment]:
    """Return appointments the actor is authorized to see for one clinic."""
    today = on_date or timezone.localdate()
    if status and status not in AppointmentStatus.values:
        status = ""

    queryset = Appointment.objects.for_clinic(clinic_id)

    is_patient = has_active_clinic_role(
        clinic_id=clinic_id, user_id=actor.pk, role="patient", on_date=today
    )
    if is_patient:
        profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
        if profile is None:
            return []
        queryset = queryset.filter(patient_profile_id=profile.pk)
    elif has_active_clinic_role(
        clinic_id=clinic_id, user_id=actor.pk, role="therapist", on_date=today
    ):
        linked = linked_patients_for_therapist(
            clinic_id=clinic_id, therapist_id=actor.pk, on_date=today
        )
        profile_ids = {row.patient_profile_id for row in linked}
        if not profile_ids:
            return []
        queryset = queryset.filter(patient_profile_id__in=profile_ids)
    elif any(
        has_active_clinic_role(
            clinic_id=clinic_id, user_id=actor.pk, role=role, on_date=today
        )
        for role in ("clinic_admin", "administrative_staff")
    ):
        pass  # full clinic scope
    else:
        return []

    if status:
        queryset = queryset.filter(status=status)
    if from_at is not None:
        queryset = queryset.filter(start_at__gte=from_at)
    if to_at is not None:
        queryset = queryset.filter(start_at__lt=to_at)
    return list(queryset.order_by("start_at", "id"))


def conversations_for_actor(
    *, clinic_id: UUID, actor: AbstractBaseUser
) -> list[Conversation]:
    """Return conversations in which the actor is an active participant."""
    return list(
        Conversation.objects.for_clinic(clinic_id)
        .filter(
            participants__user_id=actor.pk,
            participants__is_active=True,
            is_active=True,
        )
        .order_by("-created_at")
    )


def messages_for_conversation(
    *, clinic_id: UUID, actor: AbstractBaseUser, conversation_id: UUID
) -> list[Message]:
    """Return one conversation's messages only for an active participant."""
    participant = (
        ConversationParticipant.objects.for_clinic(clinic_id)
        .filter(
            conversation_id=conversation_id,
            user_id=actor.pk,
            is_active=True,
        )
        .first()
    )
    if participant is None:
        return []
    return list(
        Message.objects.for_clinic(clinic_id)
        .filter(conversation_id=conversation_id)
        .order_by("created_at", "id")
    )


def reminder_preferences_for_patient(
    *, clinic_id: UUID, actor: AbstractBaseUser
) -> list[ReminderPreference]:
    """Return the patient's own reminder preferences."""
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None:
        return []
    return list(
        ReminderPreference.objects.for_clinic(clinic_id)
        .filter(patient_profile_id=profile.pk)
        .order_by("reminder_type", "channel")
    )


def waitlist_entries_visible_to(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    status: str = "",
) -> list[WaitlistEntry]:
    """Return waitlist entries for an authorized reception actor."""
    today = timezone.localdate()
    if not any(
        has_active_clinic_role(
            clinic_id=clinic_id, user_id=actor.pk, role=role, on_date=today
        )
        for role in ("clinic_admin", "administrative_staff")
    ):
        return []
    queryset = WaitlistEntry.objects.for_clinic(clinic_id).select_related(
        "patient_profile", "unit", "service"
    )
    if status and status in WaitlistStatus.values:
        queryset = queryset.filter(status=status)
    return list(queryset.order_by("created_at", "id"))
