"""Availability patterns, overrides and blocking windows for professionals."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.persistence import UUIDTimestampedModel


class AvailabilityPatternQuerySet(models.QuerySet["AvailabilityPattern"]):
    def for_clinic(self, clinic_id: UUID) -> AvailabilityPatternQuerySet:
        return self.filter(clinic_id=clinic_id)


class AvailabilityPatternManager(models.Manager["AvailabilityPattern"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError(
            "AvailabilityPattern queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> AvailabilityPatternQuerySet:
        return AvailabilityPatternQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureAvailabilityPatternManager(models.Manager["AvailabilityPattern"]):
    def get_queryset(self) -> AvailabilityPatternQuerySet:
        return AvailabilityPatternQuerySet(self.model, using=self._db)


class AvailabilityPattern(UUIDTimestampedModel):
    """Recurring weekly availability for one professional in a unit/room."""

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Segunda-feira"
        TUESDAY = 1, "Terça-feira"
        WEDNESDAY = 2, "Quarta-feira"
        THURSDAY = 3, "Quinta-feira"
        FRIDAY = 4, "Sexta-feira"
        SATURDAY = 5, "Sábado"
        SUNDAY = 6, "Domingo"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="availability_patterns",
    )
    professional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="availability_patterns",
    )
    unit = models.ForeignKey(
        "scheduling.Unit",
        on_delete=models.CASCADE,
        related_name="availability_patterns",
    )
    room = models.ForeignKey(
        "scheduling.Room",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="availability_patterns",
    )
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    objects = AvailabilityPatternManager()
    infrastructure_objects = InfrastructureAvailabilityPatternManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.CheckConstraint(
                condition=Q(start_time__lt=models.F("end_time")),
                name="availability_start_before_end",
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True)
                | Q(valid_until__gte=models.F("valid_from")),
                name="availability_valid_until_on_or_after_start",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "professional", "weekday", "is_active"),
                name="availability_pro_weekday_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_weekday_display()} {self.start_time}–{self.end_time}"


class AvailabilityOverrideQuerySet(models.QuerySet["AvailabilityOverride"]):
    def for_clinic(self, clinic_id: UUID) -> AvailabilityOverrideQuerySet:
        return self.filter(clinic_id=clinic_id)


class AvailabilityOverrideManager(models.Manager["AvailabilityOverride"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError(
            "AvailabilityOverride queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> AvailabilityOverrideQuerySet:
        return AvailabilityOverrideQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureAvailabilityOverrideManager(models.Manager["AvailabilityOverride"]):
    def get_queryset(self) -> AvailabilityOverrideQuerySet:
        return AvailabilityOverrideQuerySet(self.model, using=self._db)


class AvailabilityOverride(UUIDTimestampedModel):
    """One-off exception for a specific date (e.g. holiday or extra hours)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="availability_overrides",
    )
    professional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="availability_overrides",
    )
    unit = models.ForeignKey(
        "scheduling.Unit",
        on_delete=models.CASCADE,
        related_name="availability_overrides",
    )
    room = models.ForeignKey(
        "scheduling.Room",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="availability_overrides",
    )
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    available = models.BooleanField(default=False)
    reason = models.CharField(max_length=255, blank=True)

    objects = AvailabilityOverrideManager()
    infrastructure_objects = InfrastructureAvailabilityOverrideManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "professional", "unit", "date"),
                name="unique_override_per_professional_unit_date",
            ),
            models.CheckConstraint(
                condition=Q(start_time__isnull=True)
                | Q(end_time__isnull=True)
                | Q(start_time__lt=models.F("end_time")),
                name="override_start_before_end",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "professional", "date"),
                name="override_pro_date_idx",
            ),
        ]


class ScheduleBlockQuerySet(models.QuerySet["ScheduleBlock"]):
    def for_clinic(self, clinic_id: UUID) -> ScheduleBlockQuerySet:
        return self.filter(clinic_id=clinic_id)


class ScheduleBlockManager(models.Manager["ScheduleBlock"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("ScheduleBlock queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ScheduleBlockQuerySet:
        return ScheduleBlockQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureScheduleBlockManager(models.Manager["ScheduleBlock"]):
    def get_queryset(self) -> ScheduleBlockQuerySet:
        return ScheduleBlockQuerySet(self.model, using=self._db)


class ScheduleBlock(UUIDTimestampedModel):
    """One non-recurring blocking window that removes availability."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="schedule_blocks",
    )
    professional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="schedule_blocks",
    )
    unit = models.ForeignKey(
        "scheduling.Unit",
        on_delete=models.CASCADE,
        related_name="schedule_blocks",
    )
    room = models.ForeignKey(
        "scheduling.Room",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schedule_blocks",
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    reason = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    objects = ScheduleBlockManager()
    infrastructure_objects = InfrastructureScheduleBlockManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.CheckConstraint(
                condition=Q(start_at__lt=models.F("end_at")),
                name="block_start_before_end",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "professional", "start_at", "end_at"),
                name="block_pro_window_idx",
            ),
        ]
