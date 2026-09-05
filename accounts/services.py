"""Transactional identity, invitation and authentication services."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import struct
import time
from base64 import b32decode, b32encode, b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO
from typing import Protocol
from urllib.parse import quote, urlencode
from uuid import UUID, uuid4

import segno
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from clinics.selectors import active_clinic_ids_for_actor, active_clinics_for_actor
from clinics.services import (
    CLINIC_SESSION_KEY,
    activate_invited_membership,
    authorized_active_clinic,
    create_clinic_membership,
    is_membership_role_supported,
)
from core.services import Service as Service

from .events import account_audit_required, invitation_accepted
from .models import (
    AccountSession,
    ClinicInvitation,
    MFARecoveryCode,
    User,
    UserManager,
    UserMFA,
    _session_digest,
)

INVALID_INVITATION_MESSAGE = "Convite inválido ou expirado."
GENERIC_LOGIN_ERROR = "Não foi possível entrar com os dados informados."
GENERIC_RECOVERY_RESPONSE = (
    "Se existir uma conta ativa para este e-mail, você receberá as instruções."
)
logger = logging.getLogger("application.accounts")


class ClinicIdentity(Protocol):
    """Public tenant identity needed by authentication orchestration."""

    @property
    def id(self) -> UUID:
        """Return the stable tenant identifier."""
        ...

    @property
    def pk(self) -> UUID:
        """Return the stable primary key alias."""
        ...


class LoginRejectedError(ValueError):
    """Reject authentication without exposing which check failed."""


class LoginRateLimitedError(LoginRejectedError):
    """Reject authentication after the configured failure budget."""


class RecoveryRateLimitedError(ValueError):
    """Reject recovery requests after the configured request budget."""


class MFAAttemptRateLimitedError(ValueError):
    """Reject MFA verification after the configured failure budget."""


class SensitiveActionRateLimitedError(ValueError):
    """Reject repeated password reauthentication for high-impact actions."""


@dataclass(frozen=True, slots=True)
class IssuedInvitation:
    """Return the persisted invitation and its one-time raw credential."""

    invitation: ClinicInvitation
    raw_token: str


@dataclass(frozen=True, slots=True)
class TOTPEnrollmentChallenge:
    """One enrollment secret displayed once before confirmation."""

    secret: str


def _token_digest(raw_token: str) -> str:
    """Return a deterministic digest without retaining the bearer credential."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _rate_limit_key(*, scope: str, request: HttpRequest, identity: str) -> str:
    """Build a bounded cache key without retaining network or identity data."""
    network_origin = str(request.META.get("REMOTE_ADDR", "unknown"))
    digest = salted_hmac(
        f"accounts.rate-limit.{scope}",
        f"{network_origin}\0{identity}",
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()
    return f"accounts:{scope}:{digest}"


def _identity_rate_limit_key(*, scope: str, identity: str) -> str:
    """Build an account-wide pseudonymous key resistant to origin rotation."""
    digest = salted_hmac(
        f"accounts.rate-limit.{scope}.identity",
        identity,
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()
    return f"accounts:{scope}:identity:{digest}"


def _mfa_rate_limit(*, user: User, scope: str) -> tuple[str, int, int]:
    attempts, window = _rate_limit_settings(
        attempts_name="MFA_RATE_LIMIT_ATTEMPTS",
        window_name="MFA_RATE_LIMIT_WINDOW_SECONDS",
    )
    key = _identity_rate_limit_key(scope=f"mfa-{scope}", identity=str(user.pk))
    if cache.add(key, 1, timeout=window):
        reserved_attempts = 1
    else:
        try:
            reserved_attempts = cache.incr(key)
        except ValueError:
            cache.add(key, 1, timeout=window)
            reserved_attempts = 1
    if reserved_attempts > attempts:
        raise MFAAttemptRateLimitedError(
            "Muitas tentativas. Tente novamente mais tarde."
        )
    return key, attempts, window


def _rate_limit_settings(*, attempts_name: str, window_name: str) -> tuple[int, int]:
    """Return safe positive settings even if deployment input is malformed."""
    attempts = max(1, int(getattr(settings, attempts_name)))
    window = max(1, int(getattr(settings, window_name)))
    return attempts, window


def _is_rate_limited(*, key: str, attempts: int) -> bool:
    """Return whether the fixed-window counter has exhausted its budget."""
    value = cache.get(key, 0)
    return isinstance(value, int) and value >= attempts


def _record_rate_limited_action(*, key: str, window: int) -> None:
    """Atomically start or increment one fixed-window cache counter."""
    if cache.add(key, 1, timeout=window):
        return
    try:
        cache.incr(key)
    except ValueError:
        cache.add(key, 1, timeout=window)


def _request_id(request: HttpRequest) -> UUID:
    """Use request correlation when available and a safe fallback otherwise."""
    candidate = getattr(request, "request_id", None)
    try:
        return UUID(str(candidate))
    except TypeError, ValueError, AttributeError:
        return uuid4()


def _session_resource_id(request: HttpRequest) -> str:
    """Return an audit-safe digest instead of the bearer session identifier."""
    session_key = request.session.session_key or "pending-session"
    return salted_hmac(
        "accounts.audit.session",
        session_key,
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()


def _publish_account_audit(
    *,
    clinic_id: UUID,
    actor_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: str,
    request_id: UUID,
    network_origin: str | None = None,
    justification: str | None = None,
) -> None:
    """Publish one minimized audit requirement to the audit domain."""
    account_audit_required.send(
        sender=User,
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        network_origin=network_origin,
        justification=justification,
    )


def _audit_session(
    *,
    request: HttpRequest,
    clinic_id: UUID,
    actor_id: UUID,
    action: str,
) -> None:
    """Publish a minimized successful authentication lifecycle event."""
    _publish_account_audit(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=action,
        resource_type="session",
        resource_id=_session_resource_id(request),
        request_id=_request_id(request),
        network_origin=str(request.META.get("REMOTE_ADDR", "")) or None,
    )


def login_user(
    *, request: HttpRequest, email: str, password: str
) -> ClinicIdentity | None:
    """Authenticate canonically and select a tenant unless this is global staff."""
    canonical_email = UserManager.canonical_email(email)
    attempts, window = _rate_limit_settings(
        attempts_name="LOGIN_RATE_LIMIT_ATTEMPTS",
        window_name="LOGIN_RATE_LIMIT_WINDOW_SECONDS",
    )
    origin_key = _rate_limit_key(
        scope="login",
        request=request,
        identity=canonical_email,
    )
    identity_key = _identity_rate_limit_key(scope="login", identity=canonical_email)
    keys = (origin_key, identity_key)
    if any(_is_rate_limited(key=key, attempts=attempts) for key in keys):
        raise LoginRateLimitedError(GENERIC_LOGIN_ERROR)

    authenticated = authenticate(
        request,
        username=canonical_email,
        password=password,
    )
    user = authenticated if isinstance(authenticated, User) else None
    clinics = active_clinics_for_actor(user) if user is not None else []
    global_staff = user is not None and (user.is_staff or user.is_superuser)
    if user is None or (not clinics and not global_staff):
        for key in keys:
            _record_rate_limited_action(key=key, window=window)
        raise LoginRejectedError(GENERIC_LOGIN_ERROR)

    clinic = clinics[0] if clinics else None
    django_login(request, user)
    if clinic is not None:
        request.session[CLINIC_SESSION_KEY] = str(clinic.pk)
    else:
        request.session.pop(CLINIC_SESSION_KEY, None)
    register_current_session(request=request, user=user)
    cache.delete_many(keys)
    if clinic is not None:
        _audit_session(
            request=request,
            clinic_id=clinic.pk,
            actor_id=user.pk,
            action="login",
        )
    return clinic


def logout_user(*, request: HttpRequest) -> None:
    """Audit the active tenant session when possible and always flush it."""
    user = request.user if isinstance(request.user, User) else None
    raw_clinic_id = request.session.get(CLINIC_SESSION_KEY)
    try:
        clinic_id = UUID(str(raw_clinic_id))
    except TypeError, ValueError, AttributeError:
        clinic_id = None
    try:
        if user is not None and clinic_id is not None:
            allowed_clinics = {clinic.pk for clinic in active_clinics_for_actor(user)}
            if clinic_id in allowed_clinics:
                _audit_session(
                    request=request,
                    clinic_id=clinic_id,
                    actor_id=user.pk,
                    action="update",
                )
    finally:
        django_logout(request)


def request_password_recovery(*, request: HttpRequest, email: str) -> None:
    """Send a short-lived reset link while preserving a generic HTTP contract."""
    canonical_email = UserManager.canonical_email(email)
    attempts, window = _rate_limit_settings(
        attempts_name="PASSWORD_RECOVERY_RATE_LIMIT_ATTEMPTS",
        window_name="PASSWORD_RECOVERY_RATE_LIMIT_WINDOW_SECONDS",
    )
    origin_key = _rate_limit_key(
        scope="password-recovery",
        request=request,
        identity=canonical_email,
    )
    identity_key = _identity_rate_limit_key(
        scope="password-recovery", identity=canonical_email
    )
    keys = (origin_key, identity_key)
    if any(_is_rate_limited(key=key, attempts=attempts) for key in keys):
        raise RecoveryRateLimitedError(GENERIC_RECOVERY_RESPONSE)
    for key in keys:
        _record_rate_limited_action(key=key, window=window)

    user = User.objects.filter(email=canonical_email, is_active=True).first()
    if user is None or not active_clinics_for_actor(user):
        return
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse("password_reset", kwargs={"uid": uid, "token": token})
    reset_url = request.build_absolute_uri(path)
    message = EmailMultiAlternatives(
        subject="Recuperação de acesso",
        body=(
            "Recebemos uma solicitação para redefinir sua senha.\n\n"
            f"Acesse o link a seguir: {reset_url}\n\n"
            "Se você não fez esta solicitação, ignore esta mensagem."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    try:
        message.send()
    except Exception:
        logger.exception(
            "password recovery delivery failed",
            extra={"event": "accounts.password_recovery.delivery_error"},
        )


def password_reset_identity(*, uid: str, token: str) -> User | None:
    """Resolve and validate a reset credential without exposing lookup details."""
    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        user = User.objects.filter(pk=user_id, is_active=True).first()
    except ValueError, TypeError, OverflowError:
        return None
    if user is None or not default_token_generator.check_token(user, token):
        return None
    return user


@transaction.atomic
def reset_password(*, uid: str, token: str, new_password: str) -> bool:
    """Consume a reset token and invalidate every session through the auth hash."""
    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        user = (
            User.objects.select_for_update().filter(pk=user_id, is_active=True).first()
        )
    except ValueError, TypeError, OverflowError:
        return False
    if user is None or not default_token_generator.check_token(user, token):
        return False
    validate_password(new_password, user=user)

    affected_clinic_ids = active_clinic_ids_for_actor(user)
    changed_at = timezone.now()
    user.set_password(new_password)
    user.security_state_changed_at = changed_at
    user.save(
        update_fields=(
            "password",
            "credentials_changed_at",
            "security_state_changed_at",
        )
    )
    for clinic_id in affected_clinic_ids:
        _publish_account_audit(
            clinic_id=clinic_id,
            actor_id=user.pk,
            action="update",
            resource_type="user_credential",
            resource_id=str(user.pk),
            request_id=uuid4(),
            network_origin=None,
        )
    return True


def _active_clinic_for_action(
    *, clinic_id: UUID, actor: User, action: str
) -> ClinicIdentity:
    """Resolve one active tenant and enforce its current membership policy."""
    return authorized_active_clinic(
        clinic_id=clinic_id,
        actor=actor,
        action=action,
    )


def _audit_invitation(
    *, invitation: ClinicInvitation, actor_id: UUID | None, action: str
) -> None:
    """Publish one minimized invitation event without recipient or token data."""
    _publish_account_audit(
        clinic_id=invitation.clinic_id,
        actor_id=actor_id,
        action=action,
        resource_type="clinic_invitation",
        resource_id=str(invitation.id),
        request_id=uuid4(),
        network_origin=None,
    )


@transaction.atomic
def issue_invitation(
    *,
    clinic_id: UUID,
    issuer: User,
    recipient_email: str,
    initial_role: str,
    expires_at: datetime,
) -> IssuedInvitation:
    """Issue one auditable invitation for an active clinic administrator."""
    clinic = _active_clinic_for_action(
        clinic_id=clinic_id,
        actor=issuer,
        action="invitation.issue",
    )
    if expires_at <= timezone.now():
        raise ValueError(INVALID_INVITATION_MESSAGE)
    if not is_membership_role_supported(initial_role):
        raise ValueError("initial_role is invalid")
    recipient = UserManager.canonical_email(recipient_email)
    if not recipient:
        raise ValueError("recipient_email is required")

    raw_token = secrets.token_urlsafe(32)
    invitation = ClinicInvitation.infrastructure_objects.create(
        clinic_id=clinic.id,
        issuer=issuer,
        recipient_email=recipient,
        initial_role=initial_role,
        token_digest=_token_digest(raw_token),
        expires_at=expires_at,
    )
    _audit_invitation(
        invitation=invitation,
        actor_id=issuer.id,
        action="create",
    )
    return IssuedInvitation(invitation=invitation, raw_token=raw_token)


@transaction.atomic
def accept_invitation(
    *,
    raw_token: str,
    password: str,
    first_name: str,
    last_name: str,
    actor: User | None = None,
) -> User:
    """Consume one invitation for a new or explicitly authenticated identity."""
    now = timezone.now()
    invitation = (
        ClinicInvitation.infrastructure_objects.select_for_update()
        .filter(
            token_digest=_token_digest(raw_token),
            used_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=now,
            clinic__is_active=True,
        )
        .first()
    )
    if invitation is None:
        raise ValueError(INVALID_INVITATION_MESSAGE)

    existing = (
        User.objects.select_for_update()
        .filter(email=invitation.recipient_email, is_active=True)
        .first()
    )
    if existing is not None:
        if actor is None or actor.pk != existing.pk or not actor.is_authenticated:
            raise PermissionDenied
        user = existing
        if invitation.clinic_id not in active_clinic_ids_for_actor(user):
            activate_invited_membership(
                clinic_id=invitation.clinic_id,
                user_id=user.id,
                role=invitation.initial_role,
            )
    else:
        if actor is not None:
            raise PermissionDenied

        candidate = User(
            email=invitation.recipient_email,
            first_name=first_name.strip(),
            last_name=last_name.strip(),
        )
        validate_password(password, user=candidate)
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    email=candidate.email,
                    password=password,
                    first_name=candidate.first_name,
                    last_name=candidate.last_name,
                )
        except IntegrityError as error:
            raise ValueError(INVALID_INVITATION_MESSAGE) from error
        create_clinic_membership(
            clinic_id=invitation.clinic_id,
            user_id=user.id,
            role=invitation.initial_role,
        )
    invitation.used_at = now
    invitation.save(update_fields=("used_at", "updated_at"))
    _audit_invitation(
        invitation=invitation,
        actor_id=user.id,
        action="update",
    )
    invitation_accepted.send(
        sender=ClinicInvitation,
        clinic_id=invitation.clinic_id,
        invitation_id=invitation.pk,
        actor_id=user.pk,
    )
    return user


def invitation_clinic_id(*, raw_token: str) -> UUID:
    """Resolve a high-entropy invitation credential to its server-owned tenant."""
    clinic_id = (
        ClinicInvitation.infrastructure_objects.filter(
            token_digest=_token_digest(raw_token),
        )
        .values_list("clinic_id", flat=True)
        .first()
    )
    if clinic_id is None:
        raise ValueError(INVALID_INVITATION_MESSAGE)
    return clinic_id


@transaction.atomic
def revoke_invitation(
    *, clinic_id: UUID, invitation_id: UUID, actor: User
) -> ClinicInvitation:
    """Revoke one unused invitation through its tenant-scoped interface."""
    _active_clinic_for_action(
        clinic_id=clinic_id,
        actor=actor,
        action="invitation.revoke",
    )
    invitation = (
        ClinicInvitation.objects.for_clinic(clinic_id)
        .select_for_update()
        .filter(pk=invitation_id, used_at__isnull=True, revoked_at__isnull=True)
        .first()
    )
    if invitation is None:
        raise PermissionDenied
    invitation.revoked_at = timezone.now()
    invitation.revoked_by = actor
    invitation.save(update_fields=("revoked_at", "revoked_by", "updated_at"))
    _audit_invitation(
        invitation=invitation,
        actor_id=actor.id,
        action="update",
    )
    return invitation


def _client_label(request: HttpRequest) -> str:
    raw = str(request.META.get("HTTP_USER_AGENT", "Navegador desconhecido"))
    product = raw.rsplit("/", 1)[0].strip()
    return product[:120] or "Navegador desconhecido"


def _network_hint(request: HttpRequest) -> str:
    origin = str(request.META.get("REMOTE_ADDR", ""))
    if not origin:
        return ""
    return salted_hmac(
        "accounts.session-network",
        origin,
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()[:16]


def register_current_session(
    *,
    request: HttpRequest,
    user: User,
    absolute_expires_at: datetime | None = None,
) -> AccountSession:
    """Register or refresh minimized metadata for the current bearer session."""
    if request.session.session_key is None:
        request.session.save()
    session_key = request.session.session_key
    if session_key is None:
        raise RuntimeError("Authenticated session key is unavailable.")
    now = timezone.now()
    absolute_seconds = max(1, int(settings.ACCOUNT_SESSION_ABSOLUTE_SECONDS))
    digest = _session_digest(session_key)
    existing = AccountSession.objects.filter(session_key_digest=digest).first()
    if existing is not None:
        existing.last_seen_at = now
        existing.client_label = _client_label(request)
        existing.network_hint = _network_hint(request)
        existing.save(
            update_fields=(
                "last_seen_at",
                "client_label",
                "network_hint",
                "updated_at",
            )
        )
        return existing
    return AccountSession.objects.create_for_session(
        user=user,
        session_key=session_key,
        client_label=_client_label(request),
        network_hint=_network_hint(request),
        absolute_expires_at=absolute_expires_at
        or now + timedelta(seconds=absolute_seconds),
    )


@transaction.atomic
def rotate_current_session_tracking(
    *, request: HttpRequest, user: User
) -> AccountSession:
    """Replace device tracking after intentional Django session-key rotation."""
    previous = getattr(request, "account_session", None)
    previous_absolute_expiry = None
    if (
        isinstance(previous, AccountSession)
        and previous.user_id == user.pk
        and previous.revoked_at is None
    ):
        previous_absolute_expiry = previous.absolute_expires_at
        previous.revoked_at = timezone.now()
        previous.save(update_fields=("revoked_at", "updated_at"))
    return register_current_session(
        request=request,
        user=user,
        absolute_expires_at=previous_absolute_expiry,
    )


def validate_current_session(*, request: HttpRequest, user: User) -> bool:
    """Fail closed on revoked, idle, absolute-expired, or unknown sessions."""
    session_key = request.session.session_key
    if session_key is None:
        return False
    account_session = AccountSession.objects.filter(
        user=user,
        session_key_digest=_session_digest(session_key),
    ).first()
    if account_session is None:
        if not getattr(settings, "ACCOUNT_SESSION_ALLOW_UNKNOWN", False):
            return False
        account_session = register_current_session(request=request, user=user)
    now = timezone.now()
    idle_seconds = max(1, int(settings.ACCOUNT_SESSION_IDLE_SECONDS))
    expired = (
        account_session.revoked_at is not None
        or account_session.absolute_expires_at <= now
        or account_session.last_seen_at <= now - timedelta(seconds=idle_seconds)
    )
    if expired:
        if account_session.revoked_at is None:
            account_session.revoked_at = now
            account_session.save(update_fields=("revoked_at", "updated_at"))
        Session.objects.filter(session_key=session_key).delete()
        return False
    account_session.last_seen_at = now
    account_session.save(update_fields=("last_seen_at", "updated_at"))
    return True


@transaction.atomic
def revoke_account_session(
    *,
    actor: User,
    account_session_id: UUID,
    clinic_id: UUID | None = None,
) -> None:
    """Revoke one session owned by the authenticated identity."""
    account_session = (
        AccountSession.objects.select_for_update()
        .filter(
            pk=account_session_id,
            user=actor,
            revoked_at__isnull=True,
        )
        .first()
    )
    if account_session is None:
        raise PermissionDenied
    clinics = active_clinics_for_actor(actor)
    authorized_clinic_ids = {clinic.pk for clinic in clinics}
    audit_clinic_id = clinic_id or (clinics[0].pk if clinics else None)
    if audit_clinic_id is not None and audit_clinic_id not in authorized_clinic_ids:
        raise PermissionDenied
    Session.objects.filter(session_key=account_session.decrypt_session_key()).delete()
    account_session.revoked_at = timezone.now()
    account_session.save(update_fields=("revoked_at", "updated_at"))
    if audit_clinic_id is not None:
        _publish_account_audit(
            clinic_id=audit_clinic_id,
            actor_id=actor.pk,
            action="update",
            resource_type="session",
            resource_id=str(account_session.pk),
            request_id=uuid4(),
            network_origin=None,
        )


@transaction.atomic
def revoke_other_sessions(
    *,
    actor: User,
    current_session_id: UUID,
    clinic_id: UUID | None = None,
) -> int:
    """Revoke every live session except the explicitly retained current one."""
    sessions = list(
        AccountSession.objects.select_for_update()
        .filter(
            user=actor,
            revoked_at__isnull=True,
        )
        .exclude(pk=current_session_id)
    )
    clinics = active_clinics_for_actor(actor)
    authorized_clinic_ids = {clinic.pk for clinic in clinics}
    audit_clinic_id = clinic_id or (clinics[0].pk if clinics else None)
    if audit_clinic_id is not None and audit_clinic_id not in authorized_clinic_ids:
        raise PermissionDenied
    now = timezone.now()
    for account_session in sessions:
        Session.objects.filter(
            session_key=account_session.decrypt_session_key()
        ).delete()
        account_session.revoked_at = now
        account_session.save(update_fields=("revoked_at", "updated_at"))
    if audit_clinic_id is not None:
        _publish_account_audit(
            clinic_id=audit_clinic_id,
            actor_id=actor.pk,
            action="update",
            resource_type="session_set",
            resource_id=str(actor.pk),
            request_id=uuid4(),
            network_origin=None,
        )
    return len(sessions)


def reauthenticate_sensitive_action(*, actor: User, password: str) -> bool:
    """Verify the current credential immediately before a high-impact action."""
    attempts, window = _rate_limit_settings(
        attempts_name="SENSITIVE_REAUTH_RATE_LIMIT_ATTEMPTS",
        window_name="SENSITIVE_REAUTH_RATE_LIMIT_WINDOW_SECONDS",
    )
    key = _identity_rate_limit_key(scope="sensitive-reauth", identity=str(actor.pk))
    if cache.add(key, 1, timeout=window):
        reserved_attempts = 1
    else:
        try:
            reserved_attempts = cache.incr(key)
        except ValueError:
            cache.add(key, 1, timeout=window)
            reserved_attempts = 1
    if reserved_attempts > attempts:
        raise SensitiveActionRateLimitedError(
            "Muitas tentativas. Tente novamente mais tarde."
        )
    verified = bool(password) and actor.check_password(password)
    if verified:
        cache.delete(key)
    return verified


def _totp_step(at_time: int | None = None) -> int:
    return int(time.time() if at_time is None else at_time) // 30


def current_totp_code(*, secret: str, at_time: int | None = None) -> str:
    """Generate an RFC 6238 SHA-1 six-digit code for one time step."""
    step = _totp_step(at_time)
    key = b32decode(secret, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def build_totp_key_uri(*, secret: str, issuer: str, account: str) -> str:
    """Build a standards-compatible TOTP provisioning URI without side effects."""
    encoded_issuer = quote(issuer, safe="")
    encoded_account = quote(account, safe="")
    query = urlencode(
        (
            ("secret", secret),
            ("issuer", issuer),
            ("algorithm", "SHA1"),
            ("digits", "6"),
            ("period", "30"),
        ),
        quote_via=quote,
    )
    return f"otpauth://totp/{encoded_issuer}:{encoded_account}?{query}"


def build_totp_qr_data_uri(*, uri: str) -> str:
    """Generate a local SVG QR image without disclosing its payload externally."""
    output = BytesIO()
    segno.make_qr(uri, error="m").save(
        output,
        kind="svg",
        scale=6,
        border=4,
        xmldecl=False,
    )
    encoded = b64encode(output.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _recovery_digest(*, user: User, code: str) -> str:
    return salted_hmac(
        "accounts.mfa-recovery",
        f"{user.pk}:{code.strip().casefold()}",
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()


@transaction.atomic
def start_totp_enrollment(*, user: User) -> TOTPEnrollmentChallenge:
    """Replace any unconfirmed challenge and display its secret once."""
    secret = b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    mfa, _created = UserMFA.objects.select_for_update().get_or_create(
        user=user,
        defaults={"encrypted_secret": ""},
    )
    mfa.set_secret(secret)
    mfa.is_confirmed = False
    mfa.confirmed_at = None
    mfa.last_used_step = -1
    mfa.save()
    MFARecoveryCode.objects.filter(user=user).delete()
    return TOTPEnrollmentChallenge(secret=secret)


def _matching_totp_step(*, secret: str, code: str) -> int | None:
    current_step = _totp_step()
    for candidate_step in range(current_step - 1, current_step + 2):
        candidate_time = candidate_step * 30
        if hmac.compare_digest(
            current_totp_code(secret=secret, at_time=candidate_time),
            code.strip(),
        ):
            return candidate_step
    return None


@transaction.atomic
def confirm_totp_enrollment(*, user: User, code: str) -> tuple[str, ...]:
    """Confirm a challenge and return newly generated recovery codes once."""
    rate_limit_key, _attempts, _rate_limit_window = _mfa_rate_limit(
        user=user, scope="enrollment"
    )
    mfa = UserMFA.objects.select_for_update().filter(user=user).first()
    if mfa is None:
        raise ValueError("MFA enrollment was not started.")
    matched_step = _matching_totp_step(secret=mfa.decrypt_secret(), code=code)
    if matched_step is None:
        raise ValueError("Código inválido.")
    mfa.is_confirmed = True
    mfa.confirmed_at = timezone.now()
    # Confirmation activates the factor; verification consumes a TOTP step.
    mfa.last_used_step = -1
    mfa.save(
        update_fields=(
            "is_confirmed",
            "confirmed_at",
            "last_used_step",
            "updated_at",
        )
    )
    raw_codes = tuple(secrets.token_hex(5) for _index in range(8))
    MFARecoveryCode.objects.bulk_create(
        MFARecoveryCode(user=user, code_digest=_recovery_digest(user=user, code=code))
        for code in raw_codes
    )
    cache.delete(rate_limit_key)
    return raw_codes


@transaction.atomic
def consume_mfa_code(*, user: User, code: str) -> bool:
    """Consume one fresh TOTP step or one unused recovery credential."""
    rate_limit_key, _attempts, _rate_limit_window = _mfa_rate_limit(
        user=user, scope="verification"
    )
    mfa = (
        UserMFA.objects.select_for_update()
        .filter(
            user=user,
            is_confirmed=True,
        )
        .first()
    )
    if mfa is None:
        return False
    matched_step = _matching_totp_step(secret=mfa.decrypt_secret(), code=code)
    if matched_step is not None and matched_step > mfa.last_used_step:
        mfa.last_used_step = matched_step
        mfa.save(update_fields=("last_used_step", "updated_at"))
        cache.delete(rate_limit_key)
        return True
    recovery = (
        MFARecoveryCode.objects.select_for_update()
        .filter(
            user=user,
            code_digest=_recovery_digest(user=user, code=code),
            used_at__isnull=True,
        )
        .first()
    )
    if recovery is None:
        return False
    recovery.used_at = timezone.now()
    recovery.save(update_fields=("used_at", "updated_at"))
    cache.delete(rate_limit_key)
    return True


@transaction.atomic
def administratively_reset_mfa(
    *,
    clinic_id: UUID,
    actor: User,
    target_user: User,
    reason: str,
) -> None:
    """Reset MFA through an authorized and auditable administrative recovery."""
    _active_clinic_for_action(
        clinic_id=clinic_id,
        actor=actor,
        action="mfa.reset",
    )
    if actor.pk == target_user.pk or not reason.strip():
        raise PermissionDenied
    target_clinics = set(active_clinic_ids_for_actor(target_user))
    if clinic_id not in target_clinics:
        raise PermissionDenied
    UserMFA.objects.filter(user=target_user).delete()
    MFARecoveryCode.objects.filter(user=target_user).delete()
    now = timezone.now()
    live_sessions = list(
        AccountSession.objects.select_for_update().filter(
            user=target_user,
            revoked_at__isnull=True,
        )
    )
    for account_session in live_sessions:
        Session.objects.filter(
            session_key=account_session.decrypt_session_key()
        ).delete()
        account_session.revoked_at = now
        account_session.save(update_fields=("revoked_at", "updated_at"))
    target_user.security_state_changed_at = now
    target_user.save(update_fields=("security_state_changed_at",))
    _publish_account_audit(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="user_mfa",
        resource_id=str(target_user.pk),
        request_id=uuid4(),
        network_origin=None,
        justification=reason,
    )


__all__ = [
    "GENERIC_LOGIN_ERROR",
    "GENERIC_RECOVERY_RESPONSE",
    "ClinicInvitation",
    "IssuedInvitation",
    "LoginRateLimitedError",
    "LoginRejectedError",
    "MFAAttemptRateLimitedError",
    "SensitiveActionRateLimitedError",
    "RecoveryRateLimitedError",
    "Service",
    "User",
    "accept_invitation",
    "administratively_reset_mfa",
    "confirm_totp_enrollment",
    "consume_mfa_code",
    "current_totp_code",
    "invitation_clinic_id",
    "issue_invitation",
    "login_user",
    "logout_user",
    "password_reset_identity",
    "request_password_recovery",
    "reset_password",
    "register_current_session",
    "reauthenticate_sensitive_action",
    "rotate_current_session_tracking",
    "revoke_account_session",
    "revoke_invitation",
    "revoke_other_sessions",
    "start_totp_enrollment",
    "validate_current_session",
]
