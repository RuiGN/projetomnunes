"""Service layer for sleep diary, midnight tracking, and wearable sync (8.14.4)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction

from audit.services import record_audit_event
from core.services import Service as CoreService

from .contracts import FakeSleepDeviceAdapter, SleepDeviceAdapter
from .events import sleep_device_synced, sleep_entry_created
from .models import (
    SleepDeviceSyncRecord,
    SleepEntry,
    SleepProvenance,
)


class Service(CoreService[Any, Any]):
    """Sleep domain service base."""


@transaction.atomic
def record_sleep_entry(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    reference_date: date,
    bedtime: datetime,
    wake_time: datetime,
    sleep_attempt_time: datetime | None = None,
    out_of_bed_time: datetime | None = None,
    perceived_quality: int = 3,
    nap_duration_minutes: int = 0,
    notes: str = "",
    provenance: str = SleepProvenance.SELF_REPORTED,
    external_record_id: str = "",
) -> SleepEntry:
    """Record a self-reported or device sleep entry with interval checks."""
    if wake_time <= bedtime:
        raise ValidationError(
            "Horário de despertar deve ser posterior ao horário de deitar."
        )

    duration_minutes = int((wake_time - bedtime).total_seconds() / 60)
    clamped_quality = max(1, min(5, perceived_quality))

    entry, created = SleepEntry.objects.for_clinic(clinic_id).update_or_create(
        patient_profile_id=patient_profile_id,
        reference_date=reference_date,
        provenance=provenance,
        defaults={
            "clinic_id": clinic_id,
            "bedtime": bedtime,
            "sleep_attempt_time": sleep_attempt_time,
            "wake_time": wake_time,
            "out_of_bed_time": out_of_bed_time,
            "duration_minutes": duration_minutes,
            "perceived_quality": clamped_quality,
            "nap_duration_minutes": max(0, nap_duration_minutes),
            "notes": notes.strip(),
            "external_record_id": external_record_id,
        },
    )

    sleep_entry_created.send(sender=SleepEntry, entry=entry)
    return entry


@transaction.atomic
def sync_external_sleep_data(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    adapter: SleepDeviceAdapter | None = None,
    user_identifier: str = "",
    cursor: str | None = None,
) -> list[SleepEntry]:
    """Import sleep intervals from wearables or mobile health APIs idempotently."""
    actual_adapter = adapter or FakeSleepDeviceAdapter()
    result = actual_adapter.sync_sleep_records(
        user_identifier=user_identifier,
        cursor=cursor,
    )

    imported_entries: list[SleepEntry] = []
    for dp in result.data_points:
        sync_rec, _ = SleepDeviceSyncRecord.objects.for_clinic(clinic_id).get_or_create(
            patient_profile_id=patient_profile_id,
            provider=dp.source_device,
            external_record_id=dp.external_record_id,
            defaults={
                "clinic_id": clinic_id,
                "sync_cursor": result.next_cursor,
                "raw_payload": {
                    "duration_minutes": dp.duration_minutes,
                    "deep_sleep_minutes": dp.deep_sleep_minutes,
                    "rem_sleep_minutes": dp.rem_sleep_minutes,
                    "light_sleep_minutes": dp.light_sleep_minutes,
                },
            },
        )

        ref_date = dp.wake_time.date()
        entry = record_sleep_entry(
            clinic_id=clinic_id,
            patient_profile_id=patient_profile_id,
            reference_date=ref_date,
            bedtime=dp.bedtime,
            wake_time=dp.wake_time,
            perceived_quality=3,
            provenance=SleepProvenance.DEVICE_IMPORTED,
            external_record_id=dp.external_record_id,
        )
        imported_entries.append(entry)

    sleep_device_synced.send(sender=SleepDeviceSyncRecord, count=len(imported_entries))
    return imported_entries


@transaction.atomic
def delete_imported_sleep_data(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    actor_id: UUID,
) -> None:
    """Delete all device-imported sleep records under LGPD consent revocation."""
    SleepEntry.objects.for_clinic(clinic_id).filter(
        patient_profile_id=patient_profile_id,
        provenance=SleepProvenance.DEVICE_IMPORTED,
    ).delete()

    SleepDeviceSyncRecord.objects.for_clinic(clinic_id).filter(
        patient_profile_id=patient_profile_id,
    ).delete()

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="routines.imported_sleep_data_deleted",
        resource_type="sleep_imported_data",
        resource_id=str(patient_profile_id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
        justification="Patient revoked consent for imported device sleep data",
    )


__all__ = [
    "Service",
    "delete_imported_sleep_data",
    "record_sleep_entry",
    "sync_external_sleep_data",
]
