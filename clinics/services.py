"""Clinic tenant resolution and public service contracts."""

import re
from datetime import date, datetime
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from core.policies import current_actor_is_active
from core.services import (
    PrivateUploadPolicy,
    require_clean_malware_scan,
)
from core.services import (
    Service as Service,
)

from .events import clinic_configuration_updated, professional_membership_updated
from .models import Clinic, ClinicConfiguration, ClinicMembership
from .policies import ClinicAuthorizationPolicy

CLINIC_HEADER = "X-Clinic-ID"
CLINIC_SESSION_KEY = "active_clinic_id"
CLINIC_MODULE_PREREQUISITES: Final[dict[str, frozenset[str]]] = {
    "patient_management": frozenset(),
    "agenda": frozenset({"patient_management"}),
    "clinical_records": frozenset({"patient_management"}),
    "finance": frozenset(),
    "billing": frozenset({"finance"}),
    "documents": frozenset({"patient_management"}),
    "metrics": frozenset({"clinical_records"}),
    "notifications": frozenset({"patient_management"}),
}


def membership_role_choices() -> tuple[tuple[str, str], ...]:
    """Expose stable role values and PT-BR labels through the public boundary."""
    return tuple((value, str(label)) for value, label in ClinicMembership.Role.choices)


class MissingClinicSelectionError(ValueError):
    """An authenticated request supplied no explicit clinic selection."""


class InvalidClinicSelectionError(ValueError):
    """A clinic selection was not a valid UUID string."""


class UnauthorizedClinicError(PermissionError):
    """The actor has no currently active membership in the selected clinic."""


def _emit_configuration_updated(
    *,
    clinic_id: UUID,
    actor_id: UUID,
    resource_id: str,
    request_id: UUID,
) -> None:
    """Publish a minimized event for audit and other decoupled consumers."""
    clinic_configuration_updated.send(
        sender=ClinicConfiguration,
        clinic_id=clinic_id,
        actor_id=actor_id,
        resource_type="clinic_configuration",
        resource_id=resource_id,
        request_id=request_id,
    )


def selected_clinic_id(request: HttpRequest) -> UUID:
    """Parse the untrusted header, or the explicit session fallback, as a UUID."""
    raw_value: object
    if CLINIC_HEADER in request.headers:
        raw_value = request.headers[CLINIC_HEADER]
    else:
        raw_value = request.session.get(CLINIC_SESSION_KEY)
        if raw_value is None:
            raise MissingClinicSelectionError

    if not isinstance(raw_value, str) or not raw_value:
        raise InvalidClinicSelectionError

    try:
        return UUID(raw_value)
    except (ValueError, AttributeError) as exc:
        raise InvalidClinicSelectionError from exc


def resolve_request_clinic(request: HttpRequest, actor: AbstractBaseUser) -> Clinic:
    """Resolve an active clinic exclusively through a current actor membership."""
    clinic_id = selected_clinic_id(request)
    if not current_actor_is_active(actor):
        raise UnauthorizedClinicError

    today = timezone.localdate()
    membership = (
        ClinicMembership.infrastructure_objects.get_queryset()
        .active_on(today)
        .select_related("clinic")
        .filter(
            clinic_id=clinic_id,
            clinic__is_active=True,
            user_id=actor.pk,
        )
        .first()
    )
    if membership is None:
        raise UnauthorizedClinicError
    return membership.clinic


def switch_active_clinic(
    request: HttpRequest,
    actor: AbstractBaseUser,
    raw_clinic_id: object,
) -> Clinic:
    """Reauthorize and persist one explicit clinic selection in the session."""
    if not isinstance(raw_clinic_id, str) or not raw_clinic_id:
        raise UnauthorizedClinicError
    try:
        clinic_id = UUID(raw_clinic_id)
    except (ValueError, AttributeError) as exc:
        raise UnauthorizedClinicError from exc
    if not current_actor_is_active(actor):
        raise UnauthorizedClinicError

    membership = (
        ClinicMembership.infrastructure_objects.get_queryset()
        .active_on(timezone.localdate())
        .select_related("clinic")
        .filter(
            clinic_id=clinic_id,
            clinic__is_active=True,
            user_id=actor.pk,
        )
        .first()
    )
    if membership is None:
        raise UnauthorizedClinicError

    request.session.cycle_key()
    request.session[CLINIC_SESSION_KEY] = str(membership.clinic.pk)
    return membership.clinic


def update_membership_role(
    *,
    actor: AbstractBaseUser,
    clinic: Clinic,
    membership_id: UUID,
    role: str,
) -> ClinicMembership:
    """Update one role only when action and target share the explicit clinic."""
    if not ClinicAuthorizationPolicy().is_allowed(actor, clinic, "membership.update"):
        raise PermissionDenied

    scoped = ClinicMembership.objects.for_clinic(clinic.pk)
    membership = scoped.filter(pk=membership_id).first()
    if membership is None:
        raise PermissionDenied
    membership.role = role
    membership.save(update_fields=("role", "updated_at"))
    return membership


@transaction.atomic
def update_professional_membership(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    membership_id: UUID,
    role: str,
    unit_name: str,
    valid_from: date,
    valid_until: date | None,
    request_id: UUID,
) -> ClinicMembership:
    """Update one professional's tenant relationship under current authorization."""
    authorized_active_clinic(
        clinic_id=clinic_id,
        actor=actor,
        action="professionals.manage",
    )
    lock_clinic_for_update(clinic_id=clinic_id)
    if role not in {
        ClinicMembership.Role.THERAPIST,
        ClinicMembership.Role.ADMINISTRATIVE_STAFF,
    }:
        raise ValidationError("Selecione um papel profissional válido.")
    if valid_until is not None and valid_until < valid_from:
        raise ValidationError("A data final não pode ser anterior à data inicial.")
    membership = (
        ClinicMembership.objects.for_clinic(clinic_id)
        .select_for_update()
        .filter(pk=membership_id)
        .first()
    )
    if membership is None:
        raise PermissionDenied
    membership.role = role
    membership.unit_name = unit_name.strip()
    membership.valid_from = valid_from
    membership.valid_until = valid_until
    membership.authorized_by_id = actor.pk
    membership.full_clean(validate_unique=False, validate_constraints=False)
    membership.save(
        update_fields=(
            "role",
            "unit_name",
            "valid_from",
            "valid_until",
            "authorized_by",
            "updated_at",
        )
    )
    professional_membership_updated.send(
        sender=ClinicMembership,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(membership.pk),
        request_id=request_id,
    )
    return membership


def _set_professional_membership_active(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    membership_id: UUID,
    is_active: bool,
    request_id: UUID,
) -> ClinicMembership:
    authorized_active_clinic(
        clinic_id=clinic_id,
        actor=actor,
        action="professionals.manage",
    )
    lock_clinic_for_update(clinic_id=clinic_id)
    membership = (
        ClinicMembership.objects.for_clinic(clinic_id)
        .select_for_update()
        .filter(
            pk=membership_id,
            role__in=(
                ClinicMembership.Role.THERAPIST,
                ClinicMembership.Role.ADMINISTRATIVE_STAFF,
            ),
        )
        .first()
    )
    if membership is None:
        raise PermissionDenied
    membership.is_active = is_active
    if is_active:
        membership.authorized_by_id = actor.pk
    membership.save(update_fields=("is_active", "authorized_by", "updated_at"))
    professional_membership_updated.send(
        sender=ClinicMembership,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(membership.pk),
        request_id=request_id,
    )
    return membership


@transaction.atomic
def suspend_professional_membership(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    membership_id: UUID,
    request_id: UUID,
) -> ClinicMembership:
    """Suspend one professional relationship without deleting history."""
    return _set_professional_membership_active(
        clinic_id=clinic_id,
        actor=actor,
        membership_id=membership_id,
        is_active=False,
        request_id=request_id,
    )


@transaction.atomic
def reactivate_professional_membership(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    membership_id: UUID,
    request_id: UUID,
) -> ClinicMembership:
    """Reactivate one professional relationship and record its authorizer."""
    return _set_professional_membership_active(
        clinic_id=clinic_id,
        actor=actor,
        membership_id=membership_id,
        is_active=True,
        request_id=request_id,
    )


@transaction.atomic
def update_clinic_identity(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    legal_name: str,
    display_name: str,
    registration_identifier: str,
    administrative_email: str,
    administrative_phone: str,
    address_line_1: str,
    address_line_2: str,
    city: str,
    region: str,
    postal_code: str,
    country_code: str,
    request_id: UUID,
) -> ClinicConfiguration:
    """Create or update minimized institutional identity for one authorized tenant."""
    clinic = authorized_active_clinic(
        clinic_id=clinic_id,
        actor=actor,
        action="clinic.manage",
    )
    lock_clinic_for_update(clinic_id=clinic_id)
    values = {
        "legal_name": legal_name.strip(),
        "display_name": display_name.strip(),
        "registration_identifier": registration_identifier.strip(),
        "administrative_email": administrative_email.strip().lower(),
        "administrative_phone": administrative_phone.strip(),
        "address_line_1": address_line_1.strip(),
        "address_line_2": address_line_2.strip(),
        "city": city.strip(),
        "region": region.strip(),
        "postal_code": postal_code.strip(),
        "country_code": country_code.strip().upper(),
    }
    required = (
        "legal_name",
        "display_name",
        "administrative_email",
        "address_line_1",
        "city",
        "region",
        "postal_code",
        "country_code",
    )
    if any(not values[field] for field in required):
        raise ValidationError("Preencha os dados institucionais obrigatórios.")
    configuration, _created = (
        ClinicConfiguration.infrastructure_objects.update_or_create(
            clinic=clinic,
            defaults=values,
        )
    )
    configuration.full_clean(validate_unique=False)
    configuration.save()

    _emit_configuration_updated(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(configuration.pk),
        request_id=request_id,
    )
    return configuration


@transaction.atomic
def update_clinic_operations(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    timezone_name: str,
    language_code: str,
    service_channels: list[str],
    weekly_hours: dict[str, list[dict[str, str]]],
    out_of_hours_instructions: str,
    request_id: UUID,
) -> ClinicConfiguration:
    """Persist validated timezone, channels and weekly operating hours."""
    authorized_active_clinic(
        clinic_id=clinic_id,
        actor=actor,
        action="clinic.manage",
    )
    lock_clinic_for_update(clinic_id=clinic_id)
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValidationError("Selecione um fuso horário IANA válido.") from exc
    if language_code not in {"pt-BR", "en-US"}:
        raise ValidationError("Selecione um idioma suportado.")
    allowed_channels = {"in_person", "video", "phone"}
    if (
        not service_channels
        or len(service_channels) != len(set(service_channels))
        or not set(service_channels) <= allowed_channels
    ):
        raise ValidationError("Selecione canais de atendimento válidos e únicos.")
    expected_days = {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }
    if set(weekly_hours) != expected_days:
        raise ValidationError("Informe os horários de todos os dias da semana.")
    normalized_hours: dict[str, list[dict[str, str]]] = {}
    for day, intervals in weekly_hours.items():
        normalized_intervals: list[dict[str, str]] = []
        previous_end: datetime | None = None
        for interval in sorted(intervals, key=lambda item: item.get("start", "")):
            if set(interval) != {"start", "end"}:
                raise ValidationError("Informe início e fim para cada intervalo.")
            try:
                start = datetime.strptime(interval["start"], "%H:%M")
                end = datetime.strptime(interval["end"], "%H:%M")
            except ValueError as exc:
                raise ValidationError("Use horários no formato HH:MM.") from exc
            if start >= end or (previous_end is not None and start < previous_end):
                raise ValidationError(
                    "Os intervalos devem ser válidos e não sobrepostos."
                )
            normalized_intervals.append(
                {"start": interval["start"], "end": interval["end"]}
            )
            previous_end = end
        normalized_hours[day] = normalized_intervals
    instructions = out_of_hours_instructions.strip()
    if len(instructions) > 1000:
        raise ValidationError("As orientações fora do horário são muito extensas.")
    try:
        configuration = (
            ClinicConfiguration.infrastructure_objects.select_for_update().get(
                clinic_id=clinic_id
            )
        )
    except ClinicConfiguration.DoesNotExist as exc:
        raise ValidationError("Conclua primeiro os dados institucionais.") from exc
    configuration.timezone_name = timezone_name
    configuration.language_code = language_code
    configuration.service_channels = service_channels
    configuration.weekly_hours = normalized_hours
    configuration.out_of_hours_instructions = instructions
    configuration.full_clean(validate_unique=False)
    configuration.save(
        update_fields=(
            "timezone_name",
            "language_code",
            "service_channels",
            "weekly_hours",
            "out_of_hours_instructions",
            "updated_at",
        )
    )

    _emit_configuration_updated(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(configuration.pk),
        request_id=request_id,
    )
    return configuration


def _relative_luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(first), _relative_luminance(second)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


@transaction.atomic
def update_clinic_branding(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    logo: UploadedFile,
    primary_color: str,
    secondary_color: str,
    request_id: UUID,
) -> ClinicConfiguration:
    """Persist a safe raster logo and accessible light/dark theme accents."""
    authorized_active_clinic(
        clinic_id=clinic_id,
        actor=actor,
        action="clinic.manage",
    )
    lock_clinic_for_update(clinic_id=clinic_id)
    color_pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")
    if not color_pattern.fullmatch(primary_color) or not color_pattern.fullmatch(
        secondary_color
    ):
        raise ValidationError("Use cores no formato hexadecimal #RRGGBB.")
    primary = primary_color.upper()
    secondary = secondary_color.upper()
    if _contrast_ratio(primary, "#FFFFFF") < 4.5:
        raise ValidationError(
            "A cor primária não tem contraste suficiente no tema claro."
        )
    if _contrast_ratio(secondary, "#111827") < 4.5:
        raise ValidationError(
            "A cor secundária não tem contraste suficiente no tema escuro."
        )
    if (logo.size or 0) > 2 * 1024 * 1024:
        raise ValidationError("O logotipo excede o limite de 2 MB.")
    metadata = PrivateUploadPolicy().validate(logo)
    if metadata.detected_media_type not in {"image/png", "image/jpeg"}:
        raise ValidationError("O logotipo deve ser PNG ou JPEG.")
    require_clean_malware_scan(logo)
    try:
        configuration = (
            ClinicConfiguration.infrastructure_objects.select_for_update().get(
                clinic_id=clinic_id
            )
        )
    except ClinicConfiguration.DoesNotExist as exc:
        raise ValidationError("Conclua primeiro os dados institucionais.") from exc
    previous_logo = configuration.logo.name
    logo.seek(0)
    configuration.logo.save(metadata.safe_name, logo, save=False)
    configuration.primary_color = primary
    configuration.secondary_color = secondary
    configuration.full_clean(validate_unique=False)
    configuration.save(
        update_fields=("logo", "primary_color", "secondary_color", "updated_at")
    )
    if previous_logo and previous_logo != configuration.logo.name:
        transaction.on_commit(lambda: configuration.logo.storage.delete(previous_logo))

    _emit_configuration_updated(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(configuration.pk),
        request_id=request_id,
    )
    return configuration


@transaction.atomic
def update_clinic_modules(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    enabled_modules: list[str],
    request_id: UUID,
) -> ClinicConfiguration:
    """Persist a closed, prerequisite-complete module set with authorship."""
    authorized_active_clinic(
        clinic_id=clinic_id,
        actor=actor,
        action="clinic.manage",
    )
    lock_clinic_for_update(clinic_id=clinic_id)
    selected = set(enabled_modules)
    if len(selected) != len(enabled_modules):
        raise ValidationError("Não repita módulos na configuração.")
    unknown = selected - CLINIC_MODULE_PREREQUISITES.keys()
    if unknown:
        raise ValidationError("A configuração contém módulos desconhecidos.")
    missing = {
        prerequisite
        for module in selected
        for prerequisite in CLINIC_MODULE_PREREQUISITES[module]
        if prerequisite not in selected
    }
    if missing:
        raise ValidationError(
            "Ative os pré-requisitos antes dos módulos dependentes: "
            + ", ".join(sorted(missing))
        )
    try:
        configuration = (
            ClinicConfiguration.infrastructure_objects.select_for_update().get(
                clinic_id=clinic_id
            )
        )
    except ClinicConfiguration.DoesNotExist as exc:
        raise ValidationError("Conclua primeiro os dados institucionais.") from exc
    configuration.enabled_modules = sorted(selected)
    configuration.modules_updated_by_id = actor.pk
    configuration.modules_updated_at = timezone.now()
    configuration.save(
        update_fields=(
            "enabled_modules",
            "modules_updated_by",
            "modules_updated_at",
            "updated_at",
        )
    )

    _emit_configuration_updated(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(configuration.pk),
        request_id=request_id,
    )
    return configuration


def authorized_active_clinic(
    *, clinic_id: UUID, actor: AbstractBaseUser, action: str
) -> Clinic:
    """Resolve one active clinic after a current action-specific authorization."""
    clinic = Clinic.objects.for_clinic(clinic_id).filter(is_active=True).first()
    if clinic is None or not ClinicAuthorizationPolicy().is_allowed(
        actor, clinic, action
    ):
        raise PermissionDenied
    return clinic


def is_membership_role_supported(role: str) -> bool:
    """Return whether a stable tenant role may be assigned."""
    return role in ClinicMembership.Role.values


def create_clinic_membership(
    *, clinic_id: UUID, user_id: UUID, role: str
) -> ClinicMembership:
    """Create one tenant membership through the clinic-owned write boundary."""
    if not is_membership_role_supported(role):
        raise ValueError("role is invalid")
    return ClinicMembership.infrastructure_objects.create(
        clinic_id=clinic_id,
        user_id=user_id,
        role=role,
        valid_from=timezone.localdate(),
    )


def suspend_expired_memberships(*, clinic_id: UUID, on_date: date) -> tuple[UUID, ...]:
    """Suspend expired memberships inside a caller-owned transaction."""
    memberships = list(
        ClinicMembership.infrastructure_objects.select_for_update().filter(
            clinic_id=clinic_id,
            is_active=True,
            valid_until__lt=on_date,
        )
    )
    for membership in memberships:
        membership.is_active = False
        membership.save(update_fields=("is_active", "updated_at"))
    return tuple(membership.pk for membership in memberships)


def activate_invited_membership(
    *, clinic_id: UUID, user_id: UUID, role: str
) -> ClinicMembership:
    """Create or reactivate a membership authorized by a fresh invitation."""
    if not is_membership_role_supported(role):
        raise ValueError("role is invalid")
    today = timezone.localdate()
    membership = (
        ClinicMembership.infrastructure_objects.select_for_update()
        .filter(clinic_id=clinic_id, user_id=user_id)
        .first()
    )
    if membership is None:
        return create_clinic_membership(
            clinic_id=clinic_id,
            user_id=user_id,
            role=role,
        )
    if (
        membership.is_active
        and membership.valid_from <= today
        and (membership.valid_until is None or membership.valid_until >= today)
    ):
        return membership
    membership.role = role
    membership.is_active = True
    membership.valid_from = today
    membership.valid_until = None
    membership.save(
        update_fields=(
            "role",
            "is_active",
            "valid_from",
            "valid_until",
            "updated_at",
        )
    )
    return membership


def clinic_exists(*, clinic_id: UUID) -> bool:
    """Return whether a clinic identifier exists without exposing its record."""
    return Clinic.infrastructure_objects.filter(pk=clinic_id).exists()


def lock_clinic_for_update(*, clinic_id: UUID) -> None:
    """Serialize a tenant-owned transaction on the clinic root row."""
    Clinic.infrastructure_objects.select_for_update().only("id").get(pk=clinic_id)


__all__ = [
    "CLINIC_HEADER",
    "CLINIC_SESSION_KEY",
    "ClinicConfiguration",
    "ClinicMembership",
    "InvalidClinicSelectionError",
    "MissingClinicSelectionError",
    "Service",
    "UnauthorizedClinicError",
    "activate_invited_membership",
    "authorized_active_clinic",
    "clinic_exists",
    "create_clinic_membership",
    "is_membership_role_supported",
    "lock_clinic_for_update",
    "resolve_request_clinic",
    "selected_clinic_id",
    "suspend_expired_memberships",
    "switch_active_clinic",
    "update_clinic_branding",
    "update_clinic_identity",
    "update_clinic_modules",
    "update_clinic_operations",
    "update_membership_role",
]
