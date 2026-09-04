"""Clinical video conferencing services and telemetry (8.13.4)."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from scheduling.selectors import appointment_for_integrations

from .contracts import FakeVideoAdapter, VideoAdapter
from .events import video_session_created
from .models import (
    VideoAccessToken,
    VideoQualityTelemetry,
    VideoSession,
    VideoSessionStatus,
)


@transaction.atomic
def create_clinical_video_session(
    *,
    clinic_id: UUID,
    appointment_id: UUID,
    adapter: VideoAdapter | None = None,
) -> VideoSession:
    """Create an on-demand ephemeral room tied to a consultation."""
    appt = appointment_for_integrations(
        clinic_id=clinic_id, appointment_id=appointment_id
    )
    if not appt:
        raise ValidationError("Consulta não encontrada para a sala de vídeo.")

    existing = (
        VideoSession.objects.for_clinic(clinic_id)
        .filter(appointment_id=appointment_id)
        .first()
    )
    if existing:
        return existing

    actual_adapter = adapter or FakeVideoAdapter()
    duration_minutes = max(1, int((appt.end_at - appt.start_at).total_seconds() / 60))
    patient_uid = appt.patient_profile.user_id or appt.professional_id
    room_result = actual_adapter.create_room(
        appointment_id=appt.id,
        scheduled_start=appt.start_at,
        duration_minutes=duration_minutes,
        host_user_id=appt.professional_id,
        participant_user_id=patient_uid,
    )

    session = VideoSession.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        appointment_id=appointment_id,
        provider="daily_co",
        room_id=room_result.room_id,
        status=VideoSessionStatus.PENDING,
        join_url=room_result.join_url,
        scheduled_start=appt.start_at,
        scheduled_end=appt.end_at,
        is_recording_enabled=False,
        fallback_url=f"https://tel.telehealth.internal/fallback/{room_result.room_id}",
    )

    video_session_created.send(sender=VideoSession, session=session)
    return session


@transaction.atomic
def generate_participant_access_token(
    *,
    session_id: UUID,
    user_id: UUID,
    role: str,
    valid_duration_minutes: int = 120,
) -> VideoAccessToken:
    """Generate an unguessable ephemeral token for room entry."""
    session = VideoSession.infrastructure_objects.filter(pk=session_id).first()
    if not session:
        raise ValidationError("Sessão de vídeo não encontrada.")

    now = timezone.now()
    expires_at = now + timedelta(minutes=valid_duration_minutes)

    token_secret = secrets.token_urlsafe(32)

    access_token = VideoAccessToken.objects.create(
        session=session,
        user_id=user_id,
        role=role,
        token=token_secret,
        expires_at=expires_at,
    )
    return access_token


def validate_room_entry(
    *,
    token_str: str,
    now: datetime | None = None,
    early_entry_grace_minutes: int = 10,
    late_entry_grace_minutes: int = 30,
) -> VideoAccessToken:
    """Validate token and enforce strict time window for entry."""
    current_time = now or timezone.now()
    access_token = (
        VideoAccessToken.objects.filter(token=token_str)
        .select_related("session")
        .first()
    )
    if not access_token:
        raise ValidationError("Token de acesso à sala de vídeo inválido.")

    if access_token.is_expired(current_time):
        raise ValidationError("Token de acesso à sala expirado.")

    session = access_token.session
    if session.status in {VideoSessionStatus.COMPLETED, VideoSessionStatus.CANCELED}:
        raise ValidationError("A sala de videoconferência já foi finalizada.")

    # Early entry check: not earlier than grace minutes before scheduled_start
    earliest_entry = session.scheduled_start - timedelta(
        minutes=early_entry_grace_minutes
    )
    if current_time < earliest_entry:
        time_label = earliest_entry.strftime("%H:%M")
        raise ValidationError(
            f"A sala ainda não está liberada. "
            f"Entrada permitida a partir de {time_label}."
        )

    # Late entry check: not later than grace minutes after scheduled_end
    latest_entry = session.scheduled_end + timedelta(minutes=late_entry_grace_minutes)
    if current_time > latest_entry:
        raise ValidationError("O período de atendimento desta sala foi encerrado.")

    return access_token


@transaction.atomic
def configure_session_recording(
    *,
    session_id: UUID,
    therapist_consented: bool,
    patient_consented: bool,
    actor_id: UUID,
) -> VideoSession:
    """Enforce strict bilateral consent before enabling recording or transcription."""
    session = (
        VideoSession.infrastructure_objects.filter(pk=session_id)
        .select_for_update()
        .first()
    )
    if not session:
        raise ValidationError("Sessão de vídeo não encontrada.")

    # Bilateral consent required
    is_allowed = therapist_consented and patient_consented
    session.is_recording_enabled = is_allowed
    session.save(update_fields=["is_recording_enabled", "updated_at"])

    record_audit_event(
        clinic_id=session.clinic_id,
        actor_id=actor_id,
        action="integration.video_recording_configured",
        resource_type="video_session",
        resource_id=str(session.id),
        outcome="success" if is_allowed else "blocked",
        request_id=uuid4(),
        network_origin=None,
    )
    return session


@transaction.atomic
def mark_device_check_completed(*, token_str: str) -> VideoAccessToken:
    """Record that camera/microphone pre-flight checks succeeded."""
    token = VideoAccessToken.objects.filter(token=token_str).first()
    if not token:
        raise ValidationError("Token não encontrado.")
    token.device_check_completed = True
    token.save(update_fields=["device_check_completed", "updated_at"])
    return token


@transaction.atomic
def enter_waiting_room(*, token_str: str) -> VideoAccessToken:
    """Place participant in waiting room once pre-flight checks are complete."""
    token = (
        VideoAccessToken.objects.filter(token=token_str)
        .select_related("session")
        .first()
    )
    if not token:
        raise ValidationError("Token não encontrado.")
    if not token.device_check_completed:
        raise ValidationError(
            "É necessário concluir o teste de dispositivos antes de entrar na sala."
        )

    token.in_waiting_room = True
    token.save(update_fields=["in_waiting_room", "updated_at"])

    session = token.session
    if session.status == VideoSessionStatus.PENDING:
        session.status = VideoSessionStatus.WAITING_ROOM
        session.save(update_fields=["status", "updated_at"])

    return token


@transaction.atomic
def admit_participant_from_waiting_room(
    *,
    session_id: UUID,
    token_str: str,
    therapist_actor_id: UUID,
) -> VideoAccessToken:
    """Therapist admits patient from waiting room into active session."""
    token = (
        VideoAccessToken.objects.filter(token=token_str, session_id=session_id)
        .select_related("session")
        .first()
    )
    if not token:
        raise ValidationError("Participante não encontrado.")

    now = timezone.now()
    token.in_waiting_room = False
    token.admitted_at = now
    token.joined_at = now
    token.save(
        update_fields=[
            "in_waiting_room",
            "admitted_at",
            "joined_at",
            "updated_at",
        ]
    )

    session = token.session
    if session.status != VideoSessionStatus.IN_PROGRESS:
        session.status = VideoSessionStatus.IN_PROGRESS
        session.opened_at = now
        session.save(update_fields=["status", "opened_at", "updated_at"])

    record_audit_event(
        clinic_id=session.clinic_id,
        actor_id=therapist_actor_id,
        action="integration.video_participant_admitted",
        resource_type="video_access_token",
        resource_id=str(token.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return token


@transaction.atomic
def record_quality_telemetry(
    *,
    session_id: UUID,
    packet_loss_percent: float,
    jitter_ms: float,
    latency_ms: float,
) -> VideoQualityTelemetry:
    """Collect quality telemetry without audio/video payloads.

    Detects network degradation.
    """
    session = VideoSession.infrastructure_objects.filter(pk=session_id).first()
    if not session:
        raise ValidationError("Sessão de vídeo não encontrada.")

    # Degradation thresholds: packet loss > 5%, jitter > 100ms, latency > 400ms
    is_degraded = (
        (packet_loss_percent > 5.0) or (jitter_ms > 100.0) or (latency_ms > 400.0)
    )
    contingency_active = is_degraded

    record = VideoQualityTelemetry.objects.create(
        session=session,
        clinic_id=session.clinic_id,
        packet_loss_percent=packet_loss_percent,
        jitter_ms=jitter_ms,
        latency_ms=latency_ms,
        degradation_detected=is_degraded,
        contingency_activated=contingency_active,
    )

    if is_degraded:
        record_audit_event(
            clinic_id=session.clinic_id,
            actor_id=None,
            action="integration.video_quality_degraded",
            resource_type="video_session",
            resource_id=str(session.id),
            outcome="warning",
            request_id=uuid4(),
            network_origin=None,
        )

    return record


@transaction.atomic
def close_video_session(
    *,
    session_id: UUID,
    actor_id: UUID,
    adapter: VideoAdapter | None = None,
) -> VideoSession:
    """Close clinical video session, calculate duration and log audit record."""
    session = (
        VideoSession.infrastructure_objects.filter(pk=session_id)
        .select_for_update()
        .first()
    )
    if not session:
        raise ValidationError("Sessão não encontrada.")

    now = timezone.now()
    session.status = VideoSessionStatus.COMPLETED
    session.closed_at = now
    session.save(update_fields=["status", "closed_at", "updated_at"])

    actual_adapter = adapter or FakeVideoAdapter()
    actual_adapter.close_room(room_id=session.room_id)

    duration_minutes = 0
    if session.opened_at:
        duration_minutes = max(1, int((now - session.opened_at).total_seconds() / 60))

    record_audit_event(
        clinic_id=session.clinic_id,
        actor_id=actor_id,
        action="integration.video_session_closed",
        resource_type="video_session",
        resource_id=str(session.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
        justification=f"duration_minutes:{duration_minutes}",
    )
    return session


__all__ = [
    "admit_participant_from_waiting_room",
    "close_video_session",
    "configure_session_recording",
    "create_clinical_video_session",
    "enter_waiting_room",
    "generate_participant_access_token",
    "mark_device_check_completed",
    "record_quality_telemetry",
    "validate_room_entry",
]
