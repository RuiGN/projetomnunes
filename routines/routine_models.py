"""Models for personal habits, routine blocks, occurrences, and check-ins."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar
from uuid import UUID

from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel

if TYPE_CHECKING:
    pass

_ModelT = TypeVar("_ModelT", bound=models.Model)


class RoutineQuerySet(models.QuerySet[_ModelT]):
    def for_clinic(
        self: RoutineQuerySet[_ModelT], clinic_id: UUID
    ) -> RoutineQuerySet[_ModelT]:
        return self.filter(clinic_id=clinic_id)


class RoutineTenantManager(models.Manager[_ModelT]):
    def get_queryset(self) -> RoutineQuerySet[_ModelT]:
        if hasattr(self, "core_filters") or hasattr(self, "instance"):
            return RoutineQuerySet(self.model, using=self._db)
        raise RuntimeError("Routine queries require .for_clinic(clinic_id).")

    def for_clinic(
        self: RoutineTenantManager[_ModelT], clinic_id: UUID
    ) -> RoutineQuerySet[_ModelT]:
        return RoutineQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureRoutineManager(models.Manager[_ModelT]):
    def get_queryset(
        self: InfrastructureRoutineManager[_ModelT],
    ) -> RoutineQuerySet[_ModelT]:
        return RoutineQuerySet(self.model, using=self._db)


class HabitFrequency(models.TextChoices):
    DAILY = "daily", "Diária"
    WEEKDAYS = "weekdays", "Dias úteis"
    SPECIFIC_DAYS = "specific_days", "Dias específicos"
    FLEXIBLE = "flexible", "Meta flexível"


class TimeOfDayWindow(models.TextChoices):
    MORNING = "morning", "Manhã"
    AFTERNOON = "afternoon", "Tarde"
    EVENING = "evening", "Noite"
    NIGHT = "night", "Madrugada"
    ANY_TIME = "any_time", "A qualquer momento"
    EXACT_TIME = "exact_time", "Horário fixo"


class HabitStatus(models.TextChoices):
    ACTIVE = "active", "Ativo"
    PAUSED = "paused", "Pausado"
    ARCHIVED = "archived", "Arquivado"


class CheckInStatus(models.TextChoices):
    COMPLETED = "completed", "Concluído"
    PARTIAL = "partial", "Parcial"
    POSTPONED = "postponed", "Adiado"
    SKIPPED = "skipped", "Ignorado"


class RoutineBlock(UUIDTimestampedModel):
    """Daily routine block (e.g. morning, bedtime) grouping activities."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="routine_blocks",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="routine_blocks",
    )
    name = models.CharField(max_length=128)
    time_window = models.CharField(
        max_length=32,
        choices=TimeOfDayWindow.choices,
        default=TimeOfDayWindow.MORNING,
    )
    start_time = models.TimeField(null=True, blank=True)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    objects = RoutineTenantManager["RoutineBlock"]()
    infrastructure_objects = InfrastructureRoutineManager["RoutineBlock"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["order", "created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.patient_profile_id})"


class Habit(UUIDTimestampedModel):
    """Personal habit or flexible goal designed without punitive streak pressure."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="habits",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="habits",
    )
    routine_block = models.ForeignKey(
        RoutineBlock,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="habits",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    frequency = models.CharField(
        max_length=32,
        choices=HabitFrequency.choices,
        default=HabitFrequency.DAILY,
    )
    active_days = models.JSONField(default=list, blank=True)
    target_count = models.IntegerField(default=1)
    time_window = models.CharField(
        max_length=32,
        choices=TimeOfDayWindow.choices,
        default=TimeOfDayWindow.ANY_TIME,
    )
    target_time = models.TimeField(null=True, blank=True)
    target_duration_minutes = models.IntegerField(default=0)
    status = models.CharField(
        max_length=32,
        choices=HabitStatus.choices,
        default=HabitStatus.ACTIVE,
    )
    paused_until = models.DateField(null=True, blank=True)
    version = models.IntegerField(default=1)
    reminder_enabled = models.BooleanField(default=False)
    reminder_lead_minutes = models.IntegerField(default=15)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    timezone_name = models.CharField(max_length=64, default="America/Sao_Paulo")
    order = models.IntegerField(default=0)

    objects = RoutineTenantManager["Habit"]()
    infrastructure_objects = InfrastructureRoutineManager["Habit"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["order", "created_at"]

    def __str__(self) -> str:
        return f"{self.title} - {self.status}"


class HabitOccurrence(UUIDTimestampedModel):
    """Daily or periodic scheduled occurrence of a habit generated idempotently."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="habit_occurrences",
    )
    habit = models.ForeignKey(
        Habit,
        on_delete=models.CASCADE,
        related_name="occurrences",
    )
    scheduled_date = models.DateField(db_index=True)
    plan_key = models.CharField(max_length=128, db_index=True)
    version = models.IntegerField(default=1)
    is_canceled = models.BooleanField(default=False)

    objects = RoutineTenantManager["HabitOccurrence"]()
    infrastructure_objects = InfrastructureRoutineManager["HabitOccurrence"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=["habit", "scheduled_date"],
                name="unique_habit_occurrence_per_date",
            )
        ]
        ordering = ["-scheduled_date"]


class HabitCheckIn(UUIDTimestampedModel):
    """Self-reported check-in with non-punitive audit trail."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="habit_checkins",
    )
    occurrence = models.OneToOneField(
        HabitOccurrence,
        on_delete=models.CASCADE,
        related_name="checkin",
    )
    status = models.CharField(
        max_length=32,
        choices=CheckInStatus.choices,
        default=CheckInStatus.COMPLETED,
    )
    intensity_level = models.IntegerField(null=True, blank=True)
    duration_minutes_executed = models.IntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    checked_in_at = models.DateTimeField(default=timezone.now)
    history = models.JSONField(default=list, blank=True)

    objects = RoutineTenantManager["HabitCheckIn"]()
    infrastructure_objects = InfrastructureRoutineManager["HabitCheckIn"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["-checked_in_at"]


__all__ = [
    "CheckInStatus",
    "Habit",
    "HabitCheckIn",
    "HabitFrequency",
    "HabitOccurrence",
    "HabitStatus",
    "InfrastructureRoutineManager",
    "RoutineBlock",
    "RoutineQuerySet",
    "RoutineTenantManager",
    "TimeOfDayWindow",
]
