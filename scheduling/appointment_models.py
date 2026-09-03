"""Appointment lifecycle and its append-only event history."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.persistence import UUIDTimestampedModel


class AppointmentStatus(models.TextChoices):
    REQUESTED = "requested", "Solicitada"
    CONFIRMED = "confirmed", "Confirmada"
    RESCHEDULE_REQUESTED = "reschedule_requested", "Remarcação solicitada"
    CANCELED = "canceled", "Cancelada"
    COMPLETED = "completed", "Realizada"
    NO_SHOW = "no_show", "Falta"


class AppointmentQuerySet(models.QuerySet["Appointment"]):
    def for_clinic(self, clinic_id: UUID) -> AppointmentQuerySet:
        return self.filter(clinic_id=clinic_id)


class AppointmentManager(models.Manager["Appointment"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Appointment queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> AppointmentQuerySet:
        return AppointmentQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureAppointmentManager(models.Manager["Appointment"]):
    def get_queryset(self) -> AppointmentQuerySet:
        return AppointmentQuerySet(self.model, using=self._db)


class Appointment(UUIDTimestampedModel):
    """One scheduled consultation with an explicit state machine."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="appointments",
    )
    service = models.ForeignKey(
        "scheduling.Service",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    professional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="appointments_as_professional",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    unit = models.ForeignKey(
        "scheduling.Unit",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    room = models.ForeignKey(
        "scheduling.Room",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="appointments",
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    status = models.CharField(
        max_length=32,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.REQUESTED,
    )
    idempotency_key = models.CharField(max_length=64)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="appointments_requested",
    )
    cancel_reason = models.CharField(max_length=255, blank=True)
    attendance_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments_attendance_recorded",
    )

    objects = AppointmentManager()
    infrastructure_objects = InfrastructureAppointmentManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "idempotency_key"),
                name="unique_appointment_idempotency_per_clinic",
            ),
            models.CheckConstraint(
                condition=Q(start_at__lt=models.F("end_at")),
                name="appointment_start_before_end",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "professional", "start_at"),
                name="appointment_pro_start_idx",
            ),
            models.Index(
                fields=("clinic", "patient_profile", "start_at"),
                name="appointment_patient_start_idx",
            ),
            models.Index(
                fields=("clinic", "status"),
                name="appointment_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.start_at:%d/%m/%Y %H:%M} — {self.get_status_display()}"


class AppointmentEventQuerySet(models.QuerySet["AppointmentEvent"]):
    def for_clinic(self, clinic_id: UUID) -> AppointmentEventQuerySet:
        return self.filter(clinic_id=clinic_id)


class AppointmentEventManager(models.Manager["AppointmentEvent"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("AppointmentEvent queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> AppointmentEventQuerySet:
        return AppointmentEventQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureAppointmentEventManager(models.Manager["AppointmentEvent"]):
    def get_queryset(self) -> AppointmentEventQuerySet:
        return AppointmentEventQuerySet(self.model, using=self._db)


class AppointmentEvent(UUIDTimestampedModel):
    """Append-only lifecycle event: actor, state, timestamp and reason."""

    class Kind(models.TextChoices):
        REQUESTED = "requested", "Solicitada"
        CONFIRMED = "confirmed", "Confirmada"
        RESCHEDULE_REQUESTED = "reschedule_requested", "Remarcação solicitada"
        CANCELED = "canceled", "Cancelada"
        COMPLETED = "completed", "Realizada"
        NO_SHOW = "no_show", "Falta"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="appointment_events",
    )
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        related_name="events",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    actor_id = models.UUIDField()
    reason = models.CharField(max_length=255, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    objects = AppointmentEventManager()
    infrastructure_objects = InfrastructureAppointmentEventManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "appointment", "created_at"),
                name="appointment_event_idx",
            ),
        ]
