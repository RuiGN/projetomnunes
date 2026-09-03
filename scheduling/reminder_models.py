"""Reminder preferences, scheduled reminders and notification delivery records."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from django.db import models

from core.persistence import UUIDTimestampedModel


class ReminderType(models.TextChoices):
    APPOINTMENT = "appointment", "Consulta"
    CHECKIN = "checkin", "Check-in"
    EXERCISE = "exercise", "Exercício"


class ReminderChannel(models.TextChoices):
    PUSH = "push", "Push"
    EMAIL = "email", "E-mail"


class ReminderStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    SENT = "sent", "Enviado"
    CANCELED = "canceled", "Cancelado"
    FAILED = "failed", "Falhou"


class ReminderPreferenceQuerySet(models.QuerySet["ReminderPreference"]):
    def for_clinic(self, clinic_id: UUID) -> ReminderPreferenceQuerySet:
        return self.filter(clinic_id=clinic_id)


class ReminderPreferenceManager(models.Manager["ReminderPreference"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("ReminderPreference queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ReminderPreferenceQuerySet:
        return ReminderPreferenceQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureReminderPreferenceManager(models.Manager["ReminderPreference"]):
    def get_queryset(self) -> ReminderPreferenceQuerySet:
        return ReminderPreferenceQuerySet(self.model, using=self._db)


class ReminderPreference(UUIDTimestampedModel):
    """Per-type, per-channel patient notification preferences."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="reminder_preferences",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="reminder_preferences",
    )
    reminder_type = models.CharField(max_length=32, choices=ReminderType.choices)
    channel = models.CharField(max_length=16, choices=ReminderChannel.choices)
    enabled = models.BooleanField(default=True)
    advance_minutes = models.PositiveSmallIntegerField(default=1440)
    silence_start = models.TimeField(null=True, blank=True)
    silence_end = models.TimeField(null=True, blank=True)
    timezone_name = models.CharField(max_length=64, default="America/Sao_Paulo")
    max_daily = models.PositiveSmallIntegerField(default=3)

    objects = ReminderPreferenceManager()
    infrastructure_objects = InfrastructureReminderPreferenceManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "patient_profile", "reminder_type", "channel"),
                name="unique_reminder_preference_per_type_channel",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "patient_profile", "reminder_type"),
                name="reminder_pref_type_idx",
            ),
        ]


class ReminderQuerySet(models.QuerySet["Reminder"]):
    def for_clinic(self, clinic_id: UUID) -> ReminderQuerySet:
        return self.filter(clinic_id=clinic_id)


class ReminderManager(models.Manager["Reminder"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Reminder queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ReminderQuerySet:
        return ReminderQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureReminderManager(models.Manager["Reminder"]):
    def get_queryset(self) -> ReminderQuerySet:
        return ReminderQuerySet(self.model, using=self._db)


class Reminder(UUIDTimestampedModel):
    """One idempotently scheduled delivery, decoupled from its content."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="reminders",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="reminders",
    )
    reminder_type = models.CharField(max_length=32, choices=ReminderType.choices)
    channel = models.CharField(max_length=16, choices=ReminderChannel.choices)
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reminders",
    )
    scheduled_for = models.DateTimeField()
    status = models.CharField(
        max_length=16, choices=ReminderStatus.choices, default=ReminderStatus.PENDING
    )
    idempotency_key = models.CharField(max_length=64)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivery_reference = models.CharField(max_length=255, blank=True)

    objects = ReminderManager()
    infrastructure_objects = InfrastructureReminderManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "idempotency_key"),
                name="unique_reminder_idempotency_per_clinic",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "status", "scheduled_for"),
                name="reminder_status_scheduled_idx",
            ),
        ]


class NotificationStatus(models.TextChoices):
    QUEUED = "queued", "Na fila"
    DELIVERED = "delivered", "Entregue"
    FAILED = "failed", "Falhou"
    SKIPPED = "skipped", "Ignorado"


class NotificationEventQuerySet(models.QuerySet["NotificationEvent"]):
    def for_clinic(self, clinic_id: UUID) -> NotificationEventQuerySet:
        return self.filter(clinic_id=clinic_id)


class NotificationEventManager(models.Manager["NotificationEvent"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("NotificationEvent queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> NotificationEventQuerySet:
        return NotificationEventQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureNotificationEventManager(models.Manager["NotificationEvent"]):
    def get_queryset(self) -> NotificationEventQuerySet:
        return NotificationEventQuerySet(self.model, using=self._db)


class NotificationEvent(UUIDTimestampedModel):
    """Delivery record without any sensitive payload, for reminders and messages."""

    class Kind(models.TextChoices):
        REMINDER = "reminder", "Lembrete"
        NEW_MESSAGE = "new_message", "Nova mensagem"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="notification_events",
    )
    recipient = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="notification_events",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    channel = models.CharField(max_length=16, choices=ReminderChannel.choices)
    status = models.CharField(
        max_length=16,
        choices=NotificationStatus.choices,
        default=NotificationStatus.QUEUED,
    )
    delivered_at = models.DateTimeField(null=True, blank=True)
    correlation_id = models.CharField(max_length=255, blank=True)

    objects = NotificationEventManager()
    infrastructure_objects = InfrastructureNotificationEventManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "recipient", "status"),
                name="notification_recipient_idx",
            ),
        ]
