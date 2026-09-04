"""PWA, Service Worker cache strategies, offline sync queue and conflict resolution.

PRD section 8.20.3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone

from .contracts import OfflineSyncConflictError
from .events import (
    offline_sync_conflict_detected,
    offline_sync_item_queued,
    offline_sync_resolved,
)
from .models import OfflineSyncQueueItem, OfflineSyncStatus

FORBIDDEN_OFFLINE_RESOURCE_TYPES: frozenset[str] = frozenset(
    {
        "medical_records",
        "progress_notes",
        "prescriptions",
        "clinical_evaluations",
        "electronic_signatures",
    }
)

ALLOWED_OFFLINE_RESOURCE_TYPES: frozenset[str] = frozenset(
    {
        "appointment_summary",
        "routines",
        "wellness_exercises",
        "educational_content",
        "patient_profile",
    }
)


def get_pwa_manifest() -> dict[str, Any]:
    """Generate the standard Web App Manifest for installable PWA."""
    return {
        "name": "Omnunes Saúde Mental",
        "short_name": "Omnunes",
        "description": "Plataforma integrada de cuidado em saúde mental.",
        "start_url": "/app/",
        "display": "standalone",
        "background_color": "#F8FAFC",
        "theme_color": "#0D9488",
        "orientation": "portrait-primary",
        "icons": [
            {
                "src": "/static/icons/icon-192x192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/static/icons/icon-512x512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
        "shortcuts": [
            {
                "name": "Minha Agenda",
                "url": "/app/agenda",
                "description": "Ver próximas consultas agendadas",
            },
            {
                "name": "Minhas Atividades",
                "url": "/app/atividades",
                "description": "Acompanhar tarefas e rotinas diárias",
            },
        ],
    }


def get_service_worker_cache_rules() -> list[dict[str, Any]]:
    """Return cache strategies per resource class.

    Ensures clinical data and signatures are strictly NetworkOnly (never cached).
    """
    return [
        {
            "class": "static_assets",
            "url_pattern": r"^/static/.*\.(?:png|jpg|jpeg|svg|css|js|woff2)$",
            "strategy": "CacheFirst",
            "max_age_seconds": 86400 * 30,  # 30 days
            "cache_name": "omnunes-static-v1",
        },
        {
            "class": "app_shell",
            "url_pattern": r"^/app/(?:shell|offline-fallback)/?$",
            "strategy": "StaleWhileRevalidate",
            "max_age_seconds": 86400 * 7,  # 7 days
            "cache_name": "omnunes-shell-v1",
        },
        {
            "class": "offline_informative_data",
            "url_pattern": r"^/api/v1/offline/(?:routines|appointment-summary)/?$",
            "strategy": "StaleWhileRevalidate",
            "max_age_seconds": 3600 * 12,  # 12 hours TTL
            "cache_name": "omnunes-offline-informative-v1",
        },
        {
            "class": "clinical_records_and_signatures",
            "url_pattern": (
                r"^/api/v1/(?:medical-records|clinical-notes|signatures)/.*$"
            ),
            "strategy": "NetworkOnly",
            "never_cache": True,
            "cache_name": "NO_CACHE",
        },
    ]


def get_offline_readable_data(
    *,
    clinic_id: UUID,
    user_id: UUID,
    resource_type: str,
    cached_payload: dict[str, Any],
    cached_at: datetime,
    ttl_seconds: int = 43200,  # 12 hours default
) -> dict[str, Any]:
    """Retrieve and validate offline cached data, verifying stale status.

    Raises ValidationError if the resource type involves regulated medical records.
    """
    if resource_type in FORBIDDEN_OFFLINE_RESOURCE_TYPES:
        raise ValidationError(
            f"Resource type '{resource_type}' is prohibited from offline "
            "caching for regulatory safety."
        )

    now = timezone.now()
    age = (now - cached_at).total_seconds()
    is_stale = age > ttl_seconds

    return {
        "clinic_id": str(clinic_id),
        "user_id": str(user_id),
        "resource_type": resource_type,
        "payload": cached_payload,
        "cached_at": cached_at.isoformat(),
        "ttl_seconds": ttl_seconds,
        "age_seconds": int(age),
        "is_stale": is_stale,
        "stale_warning": "Conteúdo desatualizado. Conecte-se para sincronizar."
        if is_stale
        else None,
    }


def enqueue_offline_action(
    *,
    clinic_id: UUID,
    user_id: UUID,
    device_id: str,
    action_type: str,
    payload: dict[str, Any],
    idempotency_token: str,
    base_version: int = 1,
) -> OfflineSyncQueueItem:
    """Enqueue an offline non-critical client mutation (e.g. check-in, preference)."""
    if action_type in FORBIDDEN_OFFLINE_RESOURCE_TYPES:
        raise ValidationError(
            f"Action '{action_type}' cannot be executed offline without "
            "real-time clinical validation."
        )

    # Check existing item with same idempotency token
    existing = (
        OfflineSyncQueueItem.objects.for_clinic(clinic_id)
        .filter(device_id=device_id, idempotency_token=idempotency_token)
        .first()
    )
    if existing:
        return existing

    item = OfflineSyncQueueItem.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        user_id=user_id,
        device_id=device_id,
        action_type=action_type,
        idempotency_token=idempotency_token,
        base_version=base_version,
        payload=payload,
        status=OfflineSyncStatus.QUEUED,
    )
    offline_sync_item_queued.send(
        sender=OfflineSyncQueueItem,
        item_id=item.id,
        clinic_id=clinic_id,
        device_id=device_id,
    )
    return item


def process_offline_sync(
    *,
    clinic_id: UUID,
    item_id: UUID,
    current_server_version: int,
    current_server_state: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Process an enqueued offline item, detecting version divergence.

    Prevents silent overwrite. Returns (status, details).
    """
    item = OfflineSyncQueueItem.objects.for_clinic(clinic_id).filter(id=item_id).first()
    if not item:
        raise ValidationError("Offline sync queue item not found.")

    if item.status in (OfflineSyncStatus.SYNCED, OfflineSyncStatus.REJECTED):
        return item.status, {
            "message": f"Item already in terminal state {item.status}."
        }

    # Version comparison: if server has progressed beyond base_version, conflict!
    if current_server_version > item.base_version:
        item.status = OfflineSyncStatus.CONFLICT
        item.conflict_details = {
            "base_version": item.base_version,
            "current_server_version": current_server_version,
            "client_state": item.payload,
            "server_state": current_server_state,
            "conflict_reason": "Server state modified while device was offline.",
        }
        item.save(update_fields=["status", "conflict_details", "updated_at"])
        offline_sync_conflict_detected.send(
            sender=OfflineSyncQueueItem,
            item_id=item.id,
            clinic_id=clinic_id,
        )
        return OfflineSyncStatus.CONFLICT, item.conflict_details

    # Clean sync
    item.status = OfflineSyncStatus.SYNCED
    item.resolved_at = timezone.now()
    item.save(update_fields=["status", "resolved_at", "updated_at"])
    return OfflineSyncStatus.SYNCED, {"applied_payload": item.payload}


def resolve_offline_conflict(
    *,
    clinic_id: UUID,
    item_id: UUID,
    resolution_choice: str,  # 'client_wins', 'server_wins', 'merged'
    resolved_payload: dict[str, Any],
) -> OfflineSyncQueueItem:
    """Explicitly resolve a conflict without silent overwrite."""
    item = OfflineSyncQueueItem.objects.for_clinic(clinic_id).filter(id=item_id).first()
    if not item:
        raise ValidationError("Offline sync item not found.")

    if item.status != OfflineSyncStatus.CONFLICT:
        raise OfflineSyncConflictError(
            f"Item is in state '{item.status}', not 'conflict'."
        )

    if resolution_choice not in ("client_wins", "server_wins", "merged"):
        raise ValidationError(f"Invalid resolution choice '{resolution_choice}'.")

    item.status = OfflineSyncStatus.SYNCED
    item.payload = resolved_payload
    item.resolved_at = timezone.now()
    item.conflict_details["resolution_choice"] = resolution_choice
    item.conflict_details["resolved_at"] = item.resolved_at.isoformat()
    item.save(
        update_fields=[
            "status",
            "payload",
            "resolved_at",
            "conflict_details",
            "updated_at",
        ]
    )

    offline_sync_resolved.send(
        sender=OfflineSyncQueueItem,
        item_id=item.id,
        clinic_id=clinic_id,
        resolution_choice=resolution_choice,
    )
    return item


def execute_remote_wipe(
    *,
    clinic_id: UUID,
    user_id: UUID,
    device_id: str,
) -> dict[str, Any]:
    """Invalidate all pending mutations and command device to wipe offline caches."""
    pending_items = OfflineSyncQueueItem.objects.for_clinic(clinic_id).filter(
        device_id=device_id,
        status__in=[OfflineSyncStatus.QUEUED, OfflineSyncStatus.CONFLICT],
    )
    count = pending_items.count()
    pending_items.update(
        status=OfflineSyncStatus.REJECTED,
        conflict_details={"wipe_reason": "remote_wipe_command_issued"},
    )

    return {
        "clinic_id": str(clinic_id),
        "user_id": str(user_id),
        "device_id": device_id,
        "wiped_pending_items_count": count,
        "command": "WIPE_LOCAL_STORAGE_AND_CACHE",
        "issued_at": timezone.now().isoformat(),
    }
