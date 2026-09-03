"""Scheduling domain models: services, units, rooms and availability.

Model modules are re-exported here so Django and type checkers discover them.
"""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from django.db import models

from core.persistence import UUIDTimestampedModel

from .appointment_models import (  # noqa: F401
    Appointment,
    AppointmentEvent,
    AppointmentStatus,
)
from .availability_models import (  # noqa: F401
    AvailabilityOverride,
    AvailabilityPattern,
    ScheduleBlock,
)
from .messaging_models import (  # noqa: F401
    Conversation,
    ConversationKind,
    ConversationParticipant,
    Message,
    MessageAttachment,
    MessageReadReceipt,
    ScanStatus,
)
from .reminder_models import (  # noqa: F401
    NotificationEvent,
    NotificationStatus,
    Reminder,
    ReminderChannel,
    ReminderPreference,
    ReminderStatus,
    ReminderType,
)
from .waitlist_models import (  # noqa: F401
    WaitlistEntry,
    WaitlistStatus,
)

__all__ = [
    "Appointment",
    "AppointmentEvent",
    "AppointmentStatus",
    "AvailabilityOverride",
    "AvailabilityPattern",
    "Conversation",
    "ConversationKind",
    "ConversationParticipant",
    "Message",
    "MessageAttachment",
    "MessageReadReceipt",
    "NotificationEvent",
    "NotificationStatus",
    "Reminder",
    "ReminderChannel",
    "ReminderPreference",
    "ReminderStatus",
    "ReminderType",
    "ScanStatus",
    "ScheduleBlock",
    "WaitlistEntry",
    "WaitlistStatus",
]


class ServiceQuerySet(models.QuerySet["Service"]):
    """Tenant-scoped service queries."""

    def for_clinic(self, clinic_id: UUID) -> ServiceQuerySet:
        return self.filter(clinic_id=clinic_id)


class ServiceManager(models.Manager["Service"]):
    """Refuse accidental global access to services."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Service queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ServiceQuerySet:
        return ServiceQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureServiceManager(models.Manager["Service"]):
    def get_queryset(self) -> ServiceQuerySet:
        return ServiceQuerySet(self.model, using=self._db)


class Service(UUIDTimestampedModel):
    """One bookable appointment type with a duration and inter-slot buffer."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="services",
    )
    name = models.CharField(max_length=255)
    duration_minutes = models.PositiveSmallIntegerField(default=50)
    buffer_minutes = models.PositiveSmallIntegerField(default=10)
    is_active = models.BooleanField(default=True)

    objects = ServiceManager()
    infrastructure_objects = InfrastructureServiceManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(fields=("clinic", "is_active"), name="service_clinic_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class UnitQuerySet(models.QuerySet["Unit"]):
    def for_clinic(self, clinic_id: UUID) -> UnitQuerySet:
        return self.filter(clinic_id=clinic_id)


class UnitManager(models.Manager["Unit"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Unit queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> UnitQuerySet:
        return UnitQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureUnitManager(models.Manager["Unit"]):
    def get_queryset(self) -> UnitQuerySet:
        return UnitQuerySet(self.model, using=self._db)


class Unit(UUIDTimestampedModel):
    """One physical clinic unit that owns rooms and availability."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="units",
    )
    name = models.CharField(max_length=255)
    address = models.JSONField(default=dict, blank=True)
    timezone_name = models.CharField(max_length=64, default="America/Sao_Paulo")
    is_active = models.BooleanField(default=True)

    objects = UnitManager()
    infrastructure_objects = InfrastructureUnitManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "name"),
                name="unique_unit_name_per_clinic",
            ),
        ]
        indexes = [
            models.Index(fields=("clinic", "is_active"), name="unit_clinic_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class RoomQuerySet(models.QuerySet["Room"]):
    def for_clinic(self, clinic_id: UUID) -> RoomQuerySet:
        return self.filter(clinic_id=clinic_id)


class RoomManager(models.Manager["Room"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Room queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> RoomQuerySet:
        return RoomQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureRoomManager(models.Manager["Room"]):
    def get_queryset(self) -> RoomQuerySet:
        return RoomQuerySet(self.model, using=self._db)


class Room(UUIDTimestampedModel):
    """One bookable room inside a unit."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="rooms",
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE,
        related_name="rooms",
    )
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    objects = RoomManager()
    infrastructure_objects = InfrastructureRoomManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("unit", "name"),
                name="unique_room_name_per_unit",
            ),
        ]
        indexes = [
            models.Index(fields=("clinic", "unit", "is_active"), name="room_unit_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.unit.name} — {self.name}"
