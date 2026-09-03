"""Waitlist persistence for reception-controlled slot filling."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from django.conf import settings
from django.db import models

from core.persistence import UUIDTimestampedModel


class WaitlistStatus(models.TextChoices):
    WAITING = "waiting", "Aguardando"
    OFFERED = "offered", "Vaga oferecida"
    FILLED = "filled", "Encaixado"
    CANCELED = "canceled", "Cancelado"


class WaitlistEntryQuerySet(models.QuerySet["WaitlistEntry"]):
    def for_clinic(self, clinic_id: UUID) -> WaitlistEntryQuerySet:
        return self.filter(clinic_id=clinic_id)


class WaitlistEntryManager(models.Manager["WaitlistEntry"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("WaitlistEntry queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> WaitlistEntryQuerySet:
        return WaitlistEntryQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureWaitlistEntryManager(models.Manager["WaitlistEntry"]):
    def get_queryset(self) -> WaitlistEntryQuerySet:
        return WaitlistEntryQuerySet(self.model, using=self._db)


class WaitlistEntry(UUIDTimestampedModel):
    """One reception-recorded waitlist request with period and unit preference.

    Stores only operational contact facts, never clinical content.
    """

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="waitlist_entries",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.PROTECT,
        related_name="waitlist_entries",
    )
    unit = models.ForeignKey(
        "scheduling.Unit",
        on_delete=models.PROTECT,
        related_name="waitlist_entries",
    )
    service = models.ForeignKey(
        "scheduling.Service",
        on_delete=models.PROTECT,
        related_name="waitlist_entries",
    )
    preferred_period = models.CharField(max_length=32, blank=True)
    contact_note = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16, choices=WaitlistStatus.choices, default=WaitlistStatus.WAITING
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="waitlist_entries_requested",
    )
    filled_appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="waitlist_fill",
    )

    objects = WaitlistEntryManager()
    infrastructure_objects = InfrastructureWaitlistEntryManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "status", "created_at"),
                name="waitlist_clinic_status_idx",
            ),
            models.Index(
                fields=("clinic", "unit", "status"),
                name="waitlist_clinic_unit_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.patient_profile_id}:{self.status}"
