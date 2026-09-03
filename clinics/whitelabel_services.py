"""Transactional services for white-label customization,
custom domains, and templates."""

from __future__ import annotations

import html
import re
import secrets
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from core.policies import current_actor_is_active

from .events import whitelabel_audit_required
from .models import (
    BrandThemeVersion,
    Clinic,
    ClinicConfiguration,
    ClinicMembership,
    CommunicationTemplate,
    CustomDomain,
)
from .policies import has_active_clinic_role

# ---------------------------------------------------------------------------
# 8.12.5.1 — Color contrast calculation and WCAG AA validation
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    """Convert hex color '#RRGGBB' to normalized RGB floats [0..1]."""
    cleaned = hex_color.strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join(c * 2 for c in cleaned)
    if len(cleaned) != 6:
        raise ValidationError(f"Formato de cor hexadecimal inválido: {hex_color}")
    try:
        r = int(cleaned[0:2], 16) / 255.0
        g = int(cleaned[2:4], 16) / 255.0
        b = int(cleaned[4:6], 16) / 255.0
    except ValueError as exc:
        raise ValidationError(f"Valor hexadecimal inválido: {hex_color}") from exc
    return r, g, b


def _channel_luminance(val: float) -> float:
    if val <= 0.04045:
        return val / 12.92
    return float(((val + 0.055) / 1.055) ** 2.4)


def relative_luminance(hex_color: str) -> float:
    """Calculate WCAG 2.2 relative luminance for an sRGB hex color."""
    r, g, b = _hex_to_rgb(hex_color)
    return (
        0.2126 * _channel_luminance(r)
        + 0.7152 * _channel_luminance(g)
        + 0.0722 * _channel_luminance(b)
    )


def calculate_contrast_ratio(foreground_hex: str, background_hex: str) -> float:
    """Calculate WCAG 2.2 contrast ratio between two hex colors."""
    lum1 = relative_luminance(foreground_hex)
    lum2 = relative_luminance(background_hex)
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def validate_brand_contrast(tokens: dict[str, Any]) -> list[str]:
    """Check required contrast pairs against WCAG AA requirements."""
    errors: list[str] = []
    text_color = tokens.get("text_color", "#151515")
    bg_color = tokens.get("background_color", "#F9FBFD")
    surface_color = tokens.get("surface_color", "#FFFFFF")
    primary_color = tokens.get("primary_color", "#6A69F5")

    # Text vs Background (>= 4.5:1)
    ratio_bg = calculate_contrast_ratio(text_color, bg_color)
    if ratio_bg < 4.5:
        errors.append(
            f"Contraste insuficiente ({ratio_bg}:1) entre texto ({text_color}) "
            f"e fundo ({bg_color}). Mínimo exigido: 4.5:1."
        )

    # Text vs Surface (>= 4.5:1)
    ratio_surface = calculate_contrast_ratio(text_color, surface_color)
    if ratio_surface < 4.5:
        errors.append(
            f"Contraste insuficiente ({ratio_surface}:1) entre texto ({text_color}) "
            f"e superfície ({surface_color}). Mínimo exigido: 4.5:1."
        )

    # Primary action vs Background (>= 3.0:1 for graphical/UI components)
    ratio_primary = calculate_contrast_ratio(primary_color, bg_color)
    if ratio_primary < 3.0:
        errors.append(
            f"Contraste insuficiente ({ratio_primary}:1) entre cor primária "
            f"({primary_color}) e fundo ({bg_color}). Mínimo exigido: 3.0:1."
        )

    return errors


def _require_clinic_admin(clinic_id: UUID, actor: AbstractBaseUser) -> None:
    if not current_actor_is_active(actor):
        raise PermissionDenied("Ator inativo.")
    is_admin = has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role=ClinicMembership.Role.CLINIC_ADMIN,
        on_date=timezone.localdate(),
    )
    if not is_admin:
        raise PermissionDenied(
            "Apenas administradores da clínica podem gerenciar white-label."
        )


def _emit_whitelabel_audit_required(
    *,
    clinic_id: UUID,
    actor_id: Any,
    action: str,
    resource_type: str,
    resource_id: str,
    request_id: UUID,
    justification: str | None = None,
) -> None:
    """Publish a minimized white-label audit request for the audit domain."""
    whitelabel_audit_required.send(
        sender=Clinic,
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        network_origin=None,
        justification=justification,
    )


@transaction.atomic
def update_brand_theme(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    tokens: dict[str, Any],
    notes: str = "",
    request_id: UUID,
) -> BrandThemeVersion:
    """Validate contrast, snapshot tokens, update configuration, and audit."""
    _require_clinic_admin(clinic_id, actor)

    contrast_errors = validate_brand_contrast(tokens)
    if contrast_errors:
        raise ValidationError({"contrast": contrast_errors})

    clinic = Clinic.infrastructure_objects.get(pk=clinic_id)
    config = ClinicConfiguration.infrastructure_objects.filter(clinic=clinic).first()
    if config:
        if "primary_color" in tokens:
            config.primary_color = tokens["primary_color"]
        if "secondary_color" in tokens:
            config.secondary_color = tokens["secondary_color"]
        if "display_name" in tokens:
            config.display_name = tokens["display_name"]
        config.save()

    latest = (
        BrandThemeVersion.infrastructure_objects.filter(clinic=clinic)
        .order_by("-version")
        .first()
    )
    next_ver = (latest.version + 1) if latest else 1

    version = BrandThemeVersion.infrastructure_objects.create(
        clinic=clinic,
        version=next_ver,
        tokens=tokens,
        notes=notes,
        created_by_id=actor.pk,
    )

    _emit_whitelabel_audit_required(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="brand_theme_version",
        resource_id=str(version.pk),
        request_id=request_id,
        justification=notes or None,
    )
    return version


@transaction.atomic
def update_brand_identity(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    icon: str,
    typography: str,
    legal_text: str,
    sender_name: str,
    sender_email: str,
    institutional_links: list[str],
    request_id: UUID,
) -> ClinicConfiguration:
    """Update the full white-label brand identity schema (8.12.5.1)."""
    _require_clinic_admin(clinic_id, actor)
    config = ClinicConfiguration.infrastructure_objects.filter(
        clinic_id=clinic_id
    ).first()
    if config is None:
        raise ValidationError("A configuração da clínica ainda não foi criada.")
    config.icon = icon.strip()
    config.typography = typography.strip()
    config.legal_text = legal_text.strip()
    config.sender_name = sender_name.strip()
    config.sender_email = sender_email.strip()
    config.institutional_links = list(institutional_links)
    config.save(
        update_fields=(
            "icon",
            "typography",
            "legal_text",
            "sender_name",
            "sender_email",
            "institutional_links",
            "updated_at",
        )
    )
    _emit_whitelabel_audit_required(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="brand_identity",
        resource_id=str(config.pk),
        request_id=request_id,
        justification="brand_identity_updated",
    )
    return config


@transaction.atomic
def rollback_brand_theme(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    target_version: int,
    request_id: UUID,
) -> BrandThemeVersion:
    """Roll back brand theme tokens to a specified version."""
    _require_clinic_admin(clinic_id, actor)

    target = BrandThemeVersion.infrastructure_objects.filter(
        clinic_id=clinic_id, version=target_version
    ).first()
    if not target:
        raise ValidationError(
            f"Versão {target_version} do tema não encontrada para esta clínica."
        )

    return update_brand_theme(
        clinic_id=clinic_id,
        actor=actor,
        tokens=target.tokens,
        notes=f"Rollback para a versão {target_version}",
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# 8.12.5.2 — Custom domain management and TLS adapter
# ---------------------------------------------------------------------------

DOMAIN_REGEX = re.compile(
    r"^(?!(https?://))[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
)


def normalize_domain(domain: str) -> str:
    cleaned = domain.strip().lower()
    if cleaned.startswith("http://"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("https://"):
        cleaned = cleaned[8:]
    cleaned = cleaned.split("/")[0].split(":")[0]
    if not DOMAIN_REGEX.match(cleaned):
        raise ValidationError(
            f"Domínio inválido: '{domain}'. Informe um FQDN válido "
            "(ex: clinica.exemplo.com.br)."
        )
    if cleaned in ("localhost", "127.0.0.1", "0.0.0.0"):
        raise ValidationError("Domínio local não permitido.")
    return cleaned


class FailClosedTlsAdapterError(Exception):
    """Raised when no production TLS adapter is configured."""


class DefaultTlsAdapter:
    """Explicitly simulated adapter: test injection only, never production.

    Every state it produces is marked as simulated so the persistence layer
    can refuse to store VERIFIED/ACTIVE outcomes derived from it.
    """

    simulated = True

    def provision_certificate(self, domain: str) -> dict[str, Any]:
        """Simulate ACME / CA certificate provisioning."""
        now = timezone.now()
        return {
            "status": "active",
            "provisioned_at": now,
            "expires_at": now + timedelta(days=90),
            "issuer": "Automated TLS CA",
            "simulated": True,
        }

    def verify_dns_challenge(self, domain: str, expected_token: str) -> bool:
        """Simulated ownership check: always passes (test adapter only)."""
        return True


class ProductionTlsAdapter:
    """Fail-closed adapter contract for real DNS/ACME integration.

    The production deployment must inject a concrete adapter through the
    TLS_ADAPTER setting; without one, verification refuses to run instead of
    fabricating a verified/TLS-active state.
    """

    simulated = False

    def __init__(self) -> None:
        raise FailClosedTlsAdapterError(
            "Nenhum adaptador TLS de produção está configurado."
            " Defina a variável TLS_ADAPTER com um adaptador homologado."
        )

    def provision_certificate(self, domain: str) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def verify_dns_challenge(
        self, domain: str, expected_token: str
    ) -> bool:  # pragma: no cover
        raise NotImplementedError


@transaction.atomic
def register_custom_domain(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    domain: str,
    request_id: UUID,
) -> CustomDomain:
    """Register a new custom domain in pending verification state."""
    _require_clinic_admin(clinic_id, actor)
    normalized = normalize_domain(domain)

    if CustomDomain.infrastructure_objects.filter(domain=normalized).exists():
        raise ValidationError(f"O domínio '{normalized}' já está em uso.")

    token = f"projetomnunes-verify={secrets.token_urlsafe(32)}"
    custom_domain = CustomDomain.infrastructure_objects.create(
        clinic_id=clinic_id,
        domain=normalized,
        verification_token=token,
        status=CustomDomain.Status.PENDING,
        created_by_id=actor.pk,
    )

    _emit_whitelabel_audit_required(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="custom_domain",
        resource_id=str(custom_domain.pk),
        request_id=request_id,
        justification=normalized,
    )
    return custom_domain


def verify_and_provision_custom_domain(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    domain_id: UUID,
    tls_adapter: Any = None,
    request_id: UUID,
) -> CustomDomain:
    """Verify ownership and provision TLS certificate (fail-closed)."""
    _require_clinic_admin(clinic_id, actor)

    custom_domain = CustomDomain.infrastructure_objects.filter(
        pk=domain_id, clinic_id=clinic_id
    ).first()
    if not custom_domain:
        raise PermissionDenied("Domínio não encontrado nesta clínica.")

    adapter = tls_adapter
    if adapter is None:
        configured = getattr(settings, "TLS_ADAPTER", None)
        adapter = configured() if configured else None
    if adapter is None:
        raise FailClosedTlsAdapterError(
            "A verificação de domínio exige um adaptador TLS configurado"
            " (TLS_ADAPTER). Operação recusada para evitar estado falso."
        )
    # External I/O deliberately runs OUTSIDE the persistence transaction so a
    # failed challenge can be persisted as FAILED without being rolled back.
    verified = adapter.verify_dns_challenge(
        custom_domain.domain, custom_domain.verification_token
    )
    tls_result: dict[str, Any] = {}
    if verified:
        tls_result = adapter.provision_certificate(custom_domain.domain)
    else:
        custom_domain.status = CustomDomain.Status.FAILED
        custom_domain.save()
        raise ValidationError("Falha na verificação de propriedade do domínio via DNS.")

    simulated = bool(getattr(adapter, "simulated", False)) or bool(
        tls_result.get("simulated", False)
    )
    with transaction.atomic():
        custom_domain.verified_at = timezone.now()
        if simulated:
            # A simulated adapter may not fabricate verified/TLS-active state.
            custom_domain.status = CustomDomain.Status.PENDING
            custom_domain.tls_status = CustomDomain.TlsStatus.PENDING
            custom_domain.tls_provisioned_at = None
            custom_domain.tls_expires_at = None
        else:
            custom_domain.status = CustomDomain.Status.VERIFIED
            custom_domain.tls_status = tls_result.get(
                "status", CustomDomain.TlsStatus.ACTIVE
            )
            custom_domain.tls_provisioned_at = tls_result.get(
                "provisioned_at", timezone.now()
            )
            custom_domain.tls_expires_at = tls_result.get(
                "expires_at", timezone.now() + timedelta(days=90)
            )
        custom_domain.save()

    _emit_whitelabel_audit_required(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="custom_domain",
        resource_id=str(custom_domain.pk),
        request_id=request_id,
        justification="custom_domain_verified",
    )
    return custom_domain


@transaction.atomic
def activate_custom_domain(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    domain_id: UUID,
    is_primary: bool = True,
    request_id: UUID,
) -> CustomDomain:
    """Activate custom domain for routing with cache population."""
    _require_clinic_admin(clinic_id, actor)

    custom_domain = CustomDomain.infrastructure_objects.filter(
        pk=domain_id, clinic_id=clinic_id
    ).first()
    if not custom_domain:
        raise PermissionDenied("Domínio não encontrado nesta clínica.")

    if custom_domain.status != CustomDomain.Status.VERIFIED:
        raise ValidationError("O domínio deve ser verificado antes da ativação.")

    if is_primary:
        CustomDomain.infrastructure_objects.filter(
            clinic_id=clinic_id, is_primary=True
        ).update(is_primary=False)

    custom_domain.status = CustomDomain.Status.ACTIVE
    custom_domain.is_primary = is_primary
    custom_domain.save()

    # Cache domain-to-clinic routing
    cache_key = f"whitelabel_domain_clinic_{custom_domain.domain}"
    cache.set(cache_key, str(clinic_id), timeout=3600)

    _emit_whitelabel_audit_required(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="custom_domain",
        resource_id=str(custom_domain.pk),
        request_id=request_id,
        justification="custom_domain_activated",
    )
    return custom_domain


@transaction.atomic
def revoke_custom_domain(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    domain_id: UUID,
    request_id: UUID,
) -> CustomDomain:
    """Revoke custom domain and invalidate cache."""
    _require_clinic_admin(clinic_id, actor)

    custom_domain = CustomDomain.infrastructure_objects.filter(
        pk=domain_id, clinic_id=clinic_id
    ).first()
    if not custom_domain:
        raise PermissionDenied("Domínio não encontrado nesta clínica.")

    custom_domain.status = CustomDomain.Status.REVOKED
    custom_domain.is_primary = False
    custom_domain.save()

    # Invalidate cache
    cache_key = f"whitelabel_domain_clinic_{custom_domain.domain}"
    cache.delete(cache_key)

    _emit_whitelabel_audit_required(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="delete",
        resource_type="custom_domain",
        resource_id=str(custom_domain.pk),
        request_id=request_id,
        justification="custom_domain_revoked",
    )
    return custom_domain


def resolve_clinic_by_custom_domain(host: str) -> Clinic | None:
    """Lookup active clinic by custom domain with fallback to None."""
    cleaned = host.split(":")[0].strip().lower()
    cache_key = f"whitelabel_domain_clinic_{cleaned}"
    cached_clinic_id = cache.get(cache_key)
    if cached_clinic_id:
        try:
            return Clinic.infrastructure_objects.filter(
                pk=UUID(cached_clinic_id), is_active=True
            ).first()
        except ValueError, TypeError:
            pass

    domain_record = (
        CustomDomain.infrastructure_objects.filter(
            domain=cleaned, status=CustomDomain.Status.ACTIVE
        )
        .select_related("clinic")
        .first()
    )
    if domain_record and domain_record.clinic.is_active:
        cache.set(cache_key, str(domain_record.clinic_id), timeout=3600)
        return domain_record.clinic
    return None


# ---------------------------------------------------------------------------
# 8.12.5.3 — Versioned communication templates
# ---------------------------------------------------------------------------

DANGEROUS_HTML_PATTERNS = [
    re.compile(r"<\s*script[^>]*>", re.IGNORECASE),
    re.compile(r"<\s*/\s*script\s*>", re.IGNORECASE),
    re.compile(r"<\s*iframe[^>]*>", re.IGNORECASE),
    re.compile(r"<\s*object[^>]*>", re.IGNORECASE),
    re.compile(r"<\s*embed[^>]*>", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"\bon\w+\s*=", re.IGNORECASE),  # onclick, onerror, onload...
]

# Allowlist for template bodies: only benign structural/inline tags and
# http(s) URLs are permitted. Anything else (active content, event handlers,
# non-http schemes) is rejected.
_ALLOWED_TEMPLATE_TAGS: frozenset[str] = frozenset(
    {
        "p",
        "br",
        "strong",
        "em",
        "b",
        "i",
        "u",
        "ul",
        "ol",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "a",
        "span",
        "div",
        "blockquote",
        "code",
        "pre",
    }
)
_ALLOWED_TEMPLATE_ATTRIBUTES: frozenset[str] = frozenset({"href", "title"})
_ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"http", "https", "mailto"})

_TAG_PATTERN = re.compile(r"<\s*/?\s*([a-zA-Z][a-zA-Z0-9]*)", re.IGNORECASE)
_ATTR_PATTERN = re.compile(r"([a-zA-Z-]+)\s*=\s*[\"']([^\"']*)[\"']")
_URL_SCHEME_PATTERN = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*):")


def sanitize_template_content(content: str) -> str:
    """Sanitize template content with an allowlist to prevent active content.

    Rejects any tag outside the allowlist, any attribute outside the allowlist,
    and any URL whose scheme is not http/https/mailto. This closes the
    denylist gaps (base, form, link, meta refresh, data:/vbscript: URIs, SVG
    handlers, CSS expression) flagged in review round 3.
    """
    for tag_match in _TAG_PATTERN.finditer(content):
        tag = tag_match.group(1).lower()
        if tag not in _ALLOWED_TEMPLATE_TAGS:
            raise ValidationError(f"Tag não permitida no modelo: <{tag}>.")
    for attr_match in _ATTR_PATTERN.finditer(content):
        attr_name = attr_match.group(1).lower()
        attr_value = attr_match.group(2)
        if attr_name not in _ALLOWED_TEMPLATE_ATTRIBUTES:
            raise ValidationError(f"Atributo não permitido no modelo: {attr_name}.")
        if attr_name == "href":
            scheme_match = _URL_SCHEME_PATTERN.match(attr_value.strip())
            if (
                scheme_match
                and scheme_match.group(1).lower() not in _ALLOWED_URL_SCHEMES
            ):
                raise ValidationError(
                    f"Esquema de URL não permitido no modelo: {attr_value}."
                )
    for pattern in DANGEROUS_HTML_PATTERNS:
        if pattern.search(content):
            raise ValidationError(
                "Conteúdo perigoso ou tags ativas (<script>, <iframe>, eventos JS) "
                "não são permitidas."
            )
    return content


VARIABLE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def validate_template_variables(body: str, allowed_variables: list[str]) -> list[str]:
    """Ensure all variables in the body are included in the allowed list."""
    used = set(VARIABLE_PATTERN.findall(body))
    allowed_set = set(allowed_variables)
    forbidden = used - allowed_set
    if forbidden:
        raise ValidationError(
            f"Variáveis não permitidas no modelo: {', '.join(sorted(forbidden))}."
        )
    return list(used)


@transaction.atomic
def create_communication_template(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    channel: str,
    purpose: str,
    subject: str,
    body: str,
    allowed_variables: list[str],
    request_id: UUID,
) -> CommunicationTemplate:
    """Create a draft communication template with sanitized body and verified
    variables."""
    _require_clinic_admin(clinic_id, actor)

    sanitize_template_content(subject)
    sanitize_template_content(body)
    validate_template_variables(body, allowed_variables)

    latest = (
        CommunicationTemplate.infrastructure_objects.filter(
            clinic_id=clinic_id, channel=channel, purpose=purpose
        )
        .order_by("-version")
        .first()
    )
    next_ver = (latest.version + 1) if latest else 1

    template = CommunicationTemplate.infrastructure_objects.create(
        clinic_id=clinic_id,
        channel=channel,
        purpose=purpose,
        version=next_ver,
        subject=subject,
        body=body,
        allowed_variables=allowed_variables,
        status=CommunicationTemplate.Status.DRAFT,
        created_by_id=actor.pk,
    )

    _emit_whitelabel_audit_required(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="communication_template",
        resource_id=str(template.pk),
        request_id=request_id,
        justification=f"{channel}:{purpose}:v{next_ver}",
    )
    return template


@transaction.atomic
def approve_and_activate_communication_template(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    template_id: UUID,
    request_id: UUID,
) -> CommunicationTemplate:
    """Approve and activate a communication template, archiving previous versions."""
    _require_clinic_admin(clinic_id, actor)

    template = CommunicationTemplate.infrastructure_objects.filter(
        pk=template_id, clinic_id=clinic_id
    ).first()
    if not template:
        raise PermissionDenied("Modelo não encontrado nesta clínica.")

    # Archive previous active version
    CommunicationTemplate.infrastructure_objects.filter(
        clinic_id=clinic_id,
        channel=template.channel,
        purpose=template.purpose,
        status=CommunicationTemplate.Status.ACTIVE,
    ).update(status=CommunicationTemplate.Status.ARCHIVED)

    template.status = CommunicationTemplate.Status.ACTIVE
    template.approved_by_id = actor.pk
    template.approved_at = timezone.now()
    template.save()

    _emit_whitelabel_audit_required(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="communication_template",
        resource_id=str(template.pk),
        request_id=request_id,
        justification=f"{template.channel}:{template.purpose}:v{template.version}",
    )
    return template


def render_communication_template(
    template: CommunicationTemplate, context: dict[str, Any]
) -> dict[str, str]:
    """Render subject and body with provided context variables."""
    # Check context keys
    for k in context:
        if k not in template.allowed_variables:
            raise ValidationError(f"Variável '{k}' não é permitida neste modelo.")

    def replace_var(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return html.escape(str(context.get(var_name, "")))

    rendered_subject = VARIABLE_PATTERN.sub(replace_var, template.subject)
    rendered_body = VARIABLE_PATTERN.sub(replace_var, template.body)
    return {"subject": rendered_subject, "body": rendered_body}


def send_test_communication(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    template_id: UUID,
    recipient_email: str,
    sample_context: dict[str, Any],
    request_id: UUID,
) -> dict[str, Any]:
    """Send test communication to administrative actor."""
    _require_clinic_admin(clinic_id, actor)

    template = CommunicationTemplate.infrastructure_objects.filter(
        pk=template_id, clinic_id=clinic_id
    ).first()
    if not template:
        raise PermissionDenied("Modelo não encontrado nesta clínica.")

    rendered = render_communication_template(template, sample_context)

    if template.channel == CommunicationTemplate.Channel.EMAIL:
        send_mail(
            subject=f"[TESTE] {rendered['subject']}",
            message=rendered["body"],
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            fail_silently=False,
        )

    _emit_whitelabel_audit_required(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="view",
        resource_type="communication_template",
        resource_id=str(template.pk),
        request_id=request_id,
        justification=f"test_sent:{recipient_email}",
    )
    if template.channel == CommunicationTemplate.Channel.EMAIL:
        return {
            "status": "sent",
            "recipient": recipient_email,
            "rendered": rendered,
        }
    # Non-email channels have no delivery transport here; report an honest
    # preview instead of a false "sent" status.
    return {
        "status": "preview",
        "recipient": recipient_email,
        "rendered": rendered,
    }


@transaction.atomic
def rollback_communication_template(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    channel: str,
    purpose: str,
    target_version: int,
    request_id: UUID,
) -> CommunicationTemplate:
    """Roll back a communication template to a prior version.

    Creates a new ACTIVE version whose subject/body are copied from the target
    version, archiving the current active version. Audited like activation.
    """
    _require_clinic_admin(clinic_id, actor)
    target = CommunicationTemplate.infrastructure_objects.filter(
        clinic_id=clinic_id,
        channel=channel,
        purpose=purpose,
        version=target_version,
    ).first()
    if target is None:
        raise ValidationError(
            f"Versão {target_version} do modelo não encontrada para esta clínica."
        )
    latest = (
        CommunicationTemplate.infrastructure_objects.filter(
            clinic_id=clinic_id, channel=channel, purpose=purpose
        )
        .order_by("-version")
        .first()
    )
    next_ver = (latest.version + 1) if latest else 1
    CommunicationTemplate.infrastructure_objects.filter(
        clinic_id=clinic_id,
        channel=channel,
        purpose=purpose,
        status=CommunicationTemplate.Status.ACTIVE,
    ).update(status=CommunicationTemplate.Status.ARCHIVED)
    rolled_back = CommunicationTemplate.infrastructure_objects.create(
        clinic_id=clinic_id,
        channel=channel,
        purpose=purpose,
        version=next_ver,
        subject=target.subject,
        body=target.body,
        allowed_variables=target.allowed_variables,
        status=CommunicationTemplate.Status.ACTIVE,
        created_by_id=actor.pk,
        approved_by_id=actor.pk,
        approved_at=timezone.now(),
    )
    _emit_whitelabel_audit_required(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="communication_template",
        resource_id=str(rolled_back.pk),
        request_id=request_id,
        justification=f"rollback:{channel}:{purpose}:v{target_version}",
    )
    return rolled_back


def renewal_due_domains(*, days_before: int = 30) -> list[CustomDomain]:
    """Return active domains whose TLS certificate expires within the window."""
    threshold = timezone.now() + timedelta(days=days_before)
    return list(
        CustomDomain.infrastructure_objects.filter(
            status=CustomDomain.Status.ACTIVE,
            tls_status=CustomDomain.TlsStatus.ACTIVE,
            tls_expires_at__isnull=False,
            tls_expires_at__lte=threshold,
        )
    )
