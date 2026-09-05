"""Tests for Sprint 20 PWA, Service Worker cache rules, and Offline Sync (8.20.3)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from integrations.models import OfflineSyncQueueItem, OfflineSyncStatus
from integrations.pwa import (
    enqueue_offline_action,
    execute_remote_wipe,
    get_offline_readable_data,
    get_pwa_manifest,
    get_service_worker_cache_rules,
    process_offline_sync,
    resolve_offline_conflict,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica PWA Mobile")


@pytest.fixture
def mobile_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="user.mobile@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


def test_pwa_manifest_and_service_worker_cache_rules() -> None:
    """Manifest declares standalone display; SW protects clinical records."""
    manifest = get_pwa_manifest()
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/app/"
    assert len(manifest["icons"]) >= 2
    assert any(s["url"] == "/app/agenda" for s in manifest["shortcuts"])

    cache_rules = get_service_worker_cache_rules()
    static_rule = next(r for r in cache_rules if r["class"] == "static_assets")
    assert static_rule["strategy"] == "CacheFirst"

    shell_rule = next(r for r in cache_rules if r["class"] == "app_shell")
    assert shell_rule["strategy"] == "StaleWhileRevalidate"

    clinical_rule = next(
        r for r in cache_rules if r["class"] == "clinical_records_and_signatures"
    )
    assert clinical_rule["strategy"] == "NetworkOnly"
    assert clinical_rule["never_cache"] is True


@pytest.mark.django_db
def test_offline_reading_allowed_and_forbidden_resources(
    test_clinic: Clinic, mobile_user: User
) -> None:
    """Offline reading is permitted for routines, but forbidden for medical records."""
    # 1. Prohibited clinical records
    for forbidden in ["medical_records", "progress_notes", "prescriptions"]:
        with pytest.raises(ValidationError, match="prohibited from offline caching"):
            get_offline_readable_data(
                clinic_id=test_clinic.id,
                user_id=mobile_user.id,
                resource_type=forbidden,
                cached_payload={"notes": "Confidential session notes"},
                cached_at=timezone.now(),
            )

    # 2. Permitted reading - fresh
    now = timezone.now()
    fresh_data = get_offline_readable_data(
        clinic_id=test_clinic.id,
        user_id=mobile_user.id,
        resource_type="routines",
        cached_payload={"routine_id": "r1", "name": "Exercício Respiratório"},
        cached_at=now,
        ttl_seconds=3600,
    )
    assert fresh_data["is_stale"] is False
    assert fresh_data["stale_warning"] is None

    # 3. Permitted reading - stale
    old_time = now - timedelta(hours=5)
    stale_data = get_offline_readable_data(
        clinic_id=test_clinic.id,
        user_id=mobile_user.id,
        resource_type="routines",
        cached_payload={"routine_id": "r1", "name": "Exercício Respiratório"},
        cached_at=old_time,
        ttl_seconds=3600,
    )
    assert stale_data["is_stale"] is True
    assert "desatualizado" in stale_data["stale_warning"]


@pytest.mark.django_db
def test_offline_sync_queue_conflict_detection_and_explicit_resolution(
    test_clinic: Clinic, mobile_user: User
) -> None:
    """Offline sync queue detects divergence and requires explicit user choice."""
    device_id = "device_android_pixel_8"

    # Enqueue offline action (e.g. routine check-in)
    item = enqueue_offline_action(
        clinic_id=test_clinic.id,
        user_id=mobile_user.id,
        device_id=device_id,
        action_type="routine_checkin",
        payload={"task_id": "t1", "completed": True, "notes": "Fiz pela manhã"},
        idempotency_token="offline_token_001",
        base_version=1,
    )
    assert item.status == OfflineSyncStatus.QUEUED

    # 1. Clean sync when server version matches base version (1 == 1)
    status, details = process_offline_sync(
        clinic_id=test_clinic.id,
        item_id=item.id,
        current_server_version=1,
        current_server_state={"task_id": "t1", "completed": False},
    )
    assert status == OfflineSyncStatus.SYNCED

    # 2. Conflict sync when server has progressed (server_version 2 > base 1)
    item2 = enqueue_offline_action(
        clinic_id=test_clinic.id,
        user_id=mobile_user.id,
        device_id=device_id,
        action_type="routine_checkin",
        payload={"task_id": "t2", "completed": True, "notes": "Fiz offline"},
        idempotency_token="offline_token_002",
        base_version=1,
    )
    status2, conflict_details = process_offline_sync(
        clinic_id=test_clinic.id,
        item_id=item2.id,
        current_server_version=2,
        current_server_state={
            "task_id": "t2",
            "completed": True,
            "notes": "Editado pelo terapeuta no portal",
        },
    )
    assert status2 == OfflineSyncStatus.CONFLICT
    assert conflict_details["current_server_version"] == 2
    assert "Server state modified" in conflict_details["conflict_reason"]

    # 3. Explicit resolution without silent overwrite
    resolved_item = resolve_offline_conflict(
        clinic_id=test_clinic.id,
        item_id=item2.id,
        resolution_choice="merged",
        resolved_payload={
            "task_id": "t2",
            "completed": True,
            "notes": "Combinado: fiz offline e terapeuta validou",
        },
    )
    assert resolved_item.status == OfflineSyncStatus.SYNCED
    assert resolved_item.conflict_details["resolution_choice"] == "merged"


@pytest.mark.django_db
def test_remote_wipe_command_invalidates_offline_queue(
    test_clinic: Clinic, mobile_user: User
) -> None:
    """Remote wipe marks pending queue items as rejected and issues wipe command."""
    device_id = "device_lost_tablet_123"

    enqueue_offline_action(
        clinic_id=test_clinic.id,
        user_id=mobile_user.id,
        device_id=device_id,
        action_type="preference_update",
        payload={"theme": "dark"},
        idempotency_token="wipe_test_token_1",
    )

    wipe_result = execute_remote_wipe(
        clinic_id=test_clinic.id,
        user_id=mobile_user.id,
        device_id=device_id,
    )
    assert wipe_result["command"] == "WIPE_LOCAL_STORAGE_AND_CACHE"
    assert wipe_result["wiped_pending_items_count"] == 1

    # Queue items for that device are rejected
    items = OfflineSyncQueueItem.objects.for_clinic(test_clinic.id).filter(
        device_id=device_id
    )
    item = items.first()
    assert item is not None
    assert item.status == OfflineSyncStatus.REJECTED
