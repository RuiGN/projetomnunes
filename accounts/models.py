"""Authentication models owned by the accounts domain."""

from __future__ import annotations

import base64
import hashlib
from typing import Any, NoReturn
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.crypto import salted_hmac

from core.persistence import UUIDTimestampedModel


def _account_cipher() -> Fernet:
    """Derive a dedicated encryption key from deployment-owned configuration."""
    material = str(getattr(settings, "MFA_ENCRYPTION_KEY", settings.SECRET_KEY))
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest())
    return Fernet(key)


def _session_digest(session_key: str) -> str:
    return salted_hmac(
        "accounts.session-device",
        session_key,
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()


def default_workspace_layout() -> str:
    """Return the configured, allowlisted initial workspace layout."""
    configured = getattr(settings, "DEFAULT_WORKSPACE_LAYOUT", "vertical")
    return configured if configured in {"vertical", "detached"} else "vertical"


class UserManager(BaseUserManager["User"]):
    """Create users from one canonical e-mail identity."""

    use_in_migrations = True

    @staticmethod
    def canonical_email(email: str) -> str:
        """Return the stable login identifier used by persistence and lookup."""
        return email.strip().casefold()

    def _create_user(
        self, email: str, password: str | None, **extra_fields: Any
    ) -> User:
        if not email:
            raise ValueError("email is required")
        user = self.model(email=self.canonical_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        """Create an unprivileged active identity."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        """Create an explicit framework administrator for operations only."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Email-authenticated identity without an implicit business role."""

    class Layout(models.TextChoices):
        VERTICAL = "vertical", "Vertical"
        DETACHED = "detached", "Destacado"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    username = models.CharField(max_length=150, blank=True, default="")
    email = models.EmailField(max_length=254, unique=True)
    preferred_layout = models.CharField(
        max_length=16,
        choices=Layout.choices,
        default=default_workspace_layout,
    )
    security_state_changed_at = models.DateTimeField(default=timezone.now)
    credentials_changed_at = models.DateTimeField(default=timezone.now)

    objects = UserManager()  # type: ignore[misc,assignment]

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []  # type: ignore[misc]

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="unique_user_email_case_insensitive",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Persist only the canonical login identifier."""
        self.email = UserManager.canonical_email(self.email)
        super().save(*args, **kwargs)

    def set_password(self, raw_password: str | None) -> None:
        """Track the last credential mutation for session security decisions."""
        super().set_password(raw_password)
        self.credentials_changed_at = timezone.now()


class InvitationScopeRequiredError(RuntimeError):
    """Raised when invitations are queried without an explicit clinic."""


class ClinicInvitationQuerySet(models.QuerySet["ClinicInvitation"]):
    """Composable invitation queries retaining an explicit tenant scope."""

    def for_clinic(self, clinic_id: UUID) -> ClinicInvitationQuerySet:
        """Restrict invitation access to one clinic."""
        return self.filter(clinic_id=clinic_id)


class ClinicInvitationManager(models.Manager["ClinicInvitation"]):
    """Tenant-safe manager requiring an explicit clinic identifier."""

    def get_queryset(self) -> NoReturn:
        """Reject unscoped invitation enumeration."""
        raise InvitationScopeRequiredError(
            "ClinicInvitation queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> ClinicInvitationQuerySet:
        """Return invitations scoped to one clinic."""
        return ClinicInvitationQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureClinicInvitationManager(models.Manager["ClinicInvitation"]):
    """Unrestricted invitation access reserved for token resolution services."""

    def get_queryset(self) -> ClinicInvitationQuerySet:
        return ClinicInvitationQuerySet(self.model, using=self._db)


class ClinicInvitation(UUIDTimestampedModel):
    """A tenant-scoped, expiring and single-use invitation credential."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    issuer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="issued_clinic_invitations",
    )
    recipient_email = models.EmailField(max_length=254)
    initial_role = models.CharField(
        max_length=64,
        choices=(
            ("clinic_admin", "Administrador da clínica"),
            ("therapist", "Terapeuta"),
            ("administrative_staff", "Equipe administrativa"),
            ("patient", "Paciente"),
        ),
    )
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="revoked_clinic_invitations",
    )

    objects = ClinicInvitationManager()
    infrastructure_objects = InfrastructureClinicInvitationManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(used_at__isnull=True)
                | models.Q(revoked_at__isnull=True),
                name="invitation_not_used_and_revoked",
            )
        ]
        indexes = [
            models.Index(
                fields=("clinic", "recipient_email", "expires_at"),
                name="invite_clinic_email_exp_idx",
            ),
            models.Index(
                fields=("clinic", "used_at", "revoked_at"),
                name="invite_clinic_state_idx",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Persist only the canonical recipient identity."""
        self.recipient_email = UserManager.canonical_email(self.recipient_email)
        super().save(*args, **kwargs)


class AccountSessionManager(models.Manager["AccountSession"]):
    """Create minimized device records without cleartext bearer keys."""

    def create_for_session(
        self,
        *,
        user: User,
        session_key: str,
        client_label: str,
        network_hint: str,
        absolute_expires_at: Any,
    ) -> AccountSession:
        encrypted = _account_cipher().encrypt(session_key.encode()).decode("ascii")
        return self.create(
            user=user,
            session_key_digest=_session_digest(session_key),
            encrypted_session_key=encrypted,
            client_label=client_label,
            network_hint=network_hint,
            absolute_expires_at=absolute_expires_at,
        )


class AccountSession(UUIDTimestampedModel):
    """Minimized, revocable metadata for one authenticated Django session."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_sessions",
    )
    session_key_digest = models.CharField(max_length=64, unique=True)
    encrypted_session_key = models.TextField()
    client_label = models.CharField(max_length=120)
    network_hint = models.CharField(max_length=64, blank=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    absolute_expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(blank=True, null=True)

    objects = AccountSessionManager()

    def decrypt_session_key(self) -> str:
        """Return the bearer key only inside a revocation operation."""
        return (
            _account_cipher()
            .decrypt(self.encrypted_session_key.encode("ascii"))
            .decode()
        )


class UserMFA(UUIDTimestampedModel):
    """One protected TOTP enrollment state per global identity."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mfa",
    )
    encrypted_secret = models.TextField()
    is_confirmed = models.BooleanField(default=False)
    confirmed_at = models.DateTimeField(blank=True, null=True)
    last_used_step = models.BigIntegerField(default=-1)

    def decrypt_secret(self) -> str:
        return _account_cipher().decrypt(self.encrypted_secret.encode("ascii")).decode()

    def set_secret(self, secret: str) -> None:
        self.encrypted_secret = (
            _account_cipher().encrypt(secret.encode()).decode("ascii")
        )


class MFARecoveryCode(UUIDTimestampedModel):
    """Hashed, single-use recovery credential for one confirmed enrollment."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mfa_recovery_codes",
    )
    code_digest = models.CharField(max_length=64)
    used_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "code_digest"),
                name="unique_mfa_recovery_code_per_user",
            )
        ]
