"""Session, device and multifactor acceptance tests for PRD 8.4.2."""

from __future__ import annotations

from base64 import b64decode
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountSession, MFARecoveryCode, User, UserMFA
from accounts.services import (
    MFAAttemptRateLimitedError,
    SensitiveActionRateLimitedError,
    _mfa_rate_limit,
    administratively_reset_mfa,
    build_totp_key_uri,
    confirm_totp_enrollment,
    consume_mfa_code,
    current_totp_code,
    reauthenticate_sensitive_action,
    register_current_session,
    revoke_account_session,
    revoke_other_sessions,
    start_totp_enrollment,
    validate_current_session,
)
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def authenticated_admin(client: Client) -> tuple[User, Clinic]:
    clinic = ClinicFactory.create()
    user = UserFactory.create()
    user.set_password("senha-sintetica-segura")
    user.save(update_fields=("password", "credentials_changed_at"))
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=user,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()
    return user, clinic


@override_settings(ACCOUNT_SESSION_ALLOW_UNKNOWN=False)
def test_login_registers_session_before_fail_closed_validation(client: Client) -> None:
    clinic = ClinicFactory.create()
    user = User.objects.create_user(
        email="login-rastreado@example.test",
        password="senha-sintetica-segura",
    )
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
    )

    response = client.post(
        reverse("account_login"),
        {
            "email": "login-rastreado@example.test",
            "password": "senha-sintetica-segura",
        },
    )

    assert response.status_code == 302
    assert AccountSession.objects.filter(user=user, revoked_at__isnull=True).exists()
    assert client.get(reverse("workspace_vertical")).status_code == 200


@override_settings(
    ACCOUNT_SESSION_IDLE_SECONDS=900,
    ACCOUNT_SESSION_ABSOLUTE_SECONDS=7200,
)
def test_registered_session_has_minimized_device_data_and_enforced_expiry(
    client: Client,
) -> None:
    user, _clinic = authenticated_admin(client)
    request = client.get("/workspace/").wsgi_request
    request.META["HTTP_USER_AGENT"] = "Synthetic Browser/1.0"
    request.META["REMOTE_ADDR"] = "198.51.100.20"

    device = register_current_session(request=request, user=user)

    assert device.session_key_digest
    assert "198.51.100.20" not in device.network_hint
    assert device.client_label == "Synthetic Browser"
    assert device.absolute_expires_at > device.created_at
    device.last_seen_at = timezone.now() - timedelta(seconds=901)
    device.save(update_fields=("last_seen_at",))
    assert validate_current_session(request=request, user=user) is False


@override_settings(ACCOUNT_SESSION_ALLOW_UNKNOWN=True)
def test_unknown_session_is_rejected_when_fail_closed_is_enabled(
    client: Client,
) -> None:
    user, _clinic = authenticated_admin(client)
    request = client.get("/workspace/").wsgi_request
    AccountSession.objects.filter(user=user).delete()

    with override_settings(ACCOUNT_SESSION_ALLOW_UNKNOWN=False):
        assert validate_current_session(request=request, user=user) is False
    assert not AccountSession.objects.filter(user=user).exists()


def test_user_can_revoke_one_or_all_other_sessions(client: Client) -> None:
    user, clinic = authenticated_admin(client)
    current_request = client.get("/workspace/").wsgi_request
    current = register_current_session(request=current_request, user=user)
    other_session = Session.objects.create(
        session_key="other-session-key",
        session_data="e30:synthetic",
        expire_date=timezone.now() + timedelta(hours=1),
    )
    other = AccountSession.objects.create_for_session(
        user=user,
        session_key=other_session.session_key,
        client_label="Outro navegador",
        network_hint="",
        absolute_expires_at=timezone.now() + timedelta(hours=1),
    )

    revoke_account_session(actor=user, account_session_id=other.pk)
    other.refresh_from_db()
    assert other.revoked_at is not None
    assert not Session.objects.filter(session_key=other_session.session_key).exists()
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        actor_id=user.pk,
        resource_type="session",
        resource_id=str(other.pk),
    ).exists()

    third_session = Session.objects.create(
        session_key="third-session-key",
        session_data="e30:synthetic",
        expire_date=timezone.now() + timedelta(hours=1),
    )
    AccountSession.objects.create_for_session(
        user=user,
        session_key=third_session.session_key,
        client_label="Terceiro navegador",
        network_hint="",
        absolute_expires_at=timezone.now() + timedelta(hours=1),
    )
    revoked = revoke_other_sessions(actor=user, current_session_id=current.pk)
    assert revoked == 1
    assert AccountSession.objects.get(pk=current.pk).revoked_at is None
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        actor_id=user.pk,
        resource_type="session_set",
    ).exists()


def test_session_revocation_audit_uses_active_clinic(client: Client) -> None:
    user, first_clinic = authenticated_admin(client)
    active_clinic = ClinicFactory.create()
    ClinicMembershipFactory.create(
        clinic=active_clinic,
        user=user,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    session = client.session
    session["active_clinic_id"] = str(active_clinic.pk)
    session.save()
    tracked = AccountSession.objects.create_for_session(
        user=user,
        session_key="tenant-audit-session",
        client_label="Outro navegador",
        network_hint="",
        absolute_expires_at=timezone.now() + timedelta(hours=1),
    )

    response = client.post(
        reverse("account_sessions"),
        {"action": "revoke", "session_id": str(tracked.pk)},
    )

    assert response.status_code == 302
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=active_clinic.pk,
        actor_id=user.pk,
        resource_type="session",
        resource_id=str(tracked.pk),
    ).exists()
    assert not AuditEvent.infrastructure_objects.filter(
        clinic_id=first_clinic.pk,
        resource_type="session",
        resource_id=str(tracked.pk),
    ).exists()


@override_settings(
    MFA_ENCRYPTION_KEY="Z0FBQUFBQnBzeW50aGV0aWMta2V5LWZvci10ZXN0cy0wMDAwMDAwMDA9"
)
def test_totp_enrollment_requires_confirmation_and_recovery_codes_are_single_use() -> (
    None
):
    user = UserFactory.create()

    challenge = start_totp_enrollment(user=user)
    mfa = UserMFA.objects.get(user=user)
    assert mfa.is_confirmed is False
    assert challenge.secret not in mfa.encrypted_secret
    code = current_totp_code(secret=challenge.secret)

    recovery_codes = confirm_totp_enrollment(user=user, code=code)

    mfa.refresh_from_db()
    assert mfa.is_confirmed is True
    assert len(recovery_codes) == 8
    assert not MFARecoveryCode.objects.filter(code_digest=recovery_codes[0]).exists()
    assert consume_mfa_code(user=user, code=recovery_codes[0]) is True
    assert consume_mfa_code(user=user, code=recovery_codes[0]) is False
    assert (
        consume_mfa_code(user=user, code=current_totp_code(secret=challenge.secret))
        is True
    )


def test_totp_key_uri_encodes_label_components_and_rfc6238_parameters() -> None:
    uri = build_totp_key_uri(
        secret="JBSWY3DPEHPK3PXP",
        issuer="Clínica São José / Produto",
        account="Pessoa+Teste@Exemplo.COM",
    )

    assert uri == (
        "otpauth://totp/"
        "Cl%C3%ADnica%20S%C3%A3o%20Jos%C3%A9%20%2F%20Produto:"
        "Pessoa%2BTeste%40Exemplo.COM"
        "?secret=JBSWY3DPEHPK3PXP"
        "&issuer=Cl%C3%ADnica%20S%C3%A3o%20Jos%C3%A9%20%2F%20Produto"
        "&algorithm=SHA1&digits=6&period=30"
    )


@override_settings(MFA_TOTP_ISSUER="Plataforma Cuidado São José")
def test_mfa_enroll_get_renders_local_qr_and_manual_key_without_cache(
    client: Client,
) -> None:
    user, _clinic = authenticated_admin(client)
    user.email = "Pessoa+Teste@Exemplo.COM"
    user.save(update_fields=("email",))

    response = client.get(reverse("mfa_enroll"))

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert any(
        template.name == "accounts/mfa_enroll.html"
        for template in response.templates
    )
    secret = UserMFA.objects.get(user=user).decrypt_secret()
    uri = response.context["totp_uri"]
    parsed = urlsplit(uri)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "otpauth"
    assert parsed.netloc == "totp"
    assert parsed.path.endswith(
        "/Plataforma%20Cuidado%20S%C3%A3o%20Jos%C3%A9:"
        "pessoa%2Bteste%40exemplo.com"
    )
    assert query == {
        "secret": [secret],
        "issuer": ["Plataforma Cuidado São José"],
        "algorithm": ["SHA1"],
        "digits": ["6"],
        "period": ["30"],
    }
    qr_data_uri = response.context["qr_data_uri"]
    assert qr_data_uri.startswith("data:image/svg+xml;base64,")
    assert b"<svg" in b64decode(qr_data_uri.partition(",")[2])
    content = response.content.decode("utf-8")
    assert secret in content
    assert "Google Authenticator" in content
    assert "otpauth://" not in content


def test_mfa_enroll_post_confirms_factor_once_and_keeps_local_continue_url(
    client: Client,
) -> None:
    user, _clinic = authenticated_admin(client)
    enrollment = client.get(reverse("mfa_enroll"))
    secret = enrollment.context["manual_secret"]
    session = client.session
    session["mfa_next"] = "https://attacker.example/redirect"
    session.save()

    response = client.post(
        reverse("mfa_enroll"),
        {"code": current_totp_code(secret=secret)},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert any(
        template.name == "accounts/mfa_recovery_codes.html"
        for template in response.templates
    )
    assert len(response.context["recovery_codes"]) == 8
    assert response.context["continue_url"] == reverse("workspace_vertical")
    assert UserMFA.objects.get(user=user).is_confirmed is True

    follow_up = client.get(reverse("mfa_enroll"))

    assert follow_up.status_code == 302
    assert follow_up.headers["Location"] == reverse("mfa_verify")
    assert not getattr(follow_up, "context", None)


def test_mfa_enroll_invalid_code_preserves_pending_secret(client: Client) -> None:
    user, _clinic = authenticated_admin(client)
    enrollment = client.get(reverse("mfa_enroll"))
    secret = enrollment.context["manual_secret"]

    response = client.post(reverse("mfa_enroll"), {"code": "000000"})

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert "Código inválido ou expirado" in response.content.decode("utf-8")
    mfa = UserMFA.objects.get(user=user)
    assert mfa.is_confirmed is False
    assert mfa.decrypt_secret() == secret


def test_confirmed_mfa_challenge_hides_provisioning_material_and_disables_cache(
    client: Client,
) -> None:
    user, _clinic = authenticated_admin(client)
    challenge = start_totp_enrollment(user=user)
    confirm_totp_enrollment(
        user=user,
        code=current_totp_code(secret=challenge.secret),
    )

    response = client.get(reverse("mfa_verify"))

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    content = response.content.decode("utf-8")
    assert challenge.secret not in content
    assert "otpauth://" not in content
    assert "data:image/svg+xml" not in content


def test_pending_mfa_enrollment_can_be_restarted_without_confirming_factor(
    client: Client,
) -> None:
    user, _clinic = authenticated_admin(client)
    first_response = client.get(reverse("mfa_enroll"))
    first_secret = first_response.context["manual_secret"]

    response = client.post(reverse("mfa_enroll"), {"action": "restart"})

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    second_secret = response.context["manual_secret"]
    assert second_secret != first_secret
    mfa = UserMFA.objects.get(user=user)
    assert mfa.decrypt_secret() == second_secret
    assert mfa.is_confirmed is False


def test_mfa_enrollment_rate_limit_response_is_not_cacheable(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticated_admin(client)
    assert client.get(reverse("mfa_enroll")).status_code == 200

    def reject_confirmation(**_kwargs: object) -> list[str]:
        raise MFAAttemptRateLimitedError

    monkeypatch.setattr("accounts.views.confirm_totp_enrollment", reject_confirmation)
    response = client.post(reverse("mfa_enroll"), {"code": "123456"})

    assert response.status_code == 429
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert response.headers["Retry-After"] == "300"


@override_settings(MFA_ENFORCEMENT_ENABLED=True)
def test_privileged_session_cannot_open_workspace_until_mfa_is_verified(
    client: Client,
) -> None:
    user, _clinic = authenticated_admin(client)

    response = client.get(reverse("workspace_vertical"))

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("mfa_enroll")
    assert user.is_authenticated


def test_user_cannot_revoke_another_identity_session(client: Client) -> None:
    user = UserFactory.create()
    other = UserFactory.create()
    session = AccountSession.objects.create_for_session(
        user=other,
        session_key="foreign-session-key",
        client_label="Outro navegador",
        network_hint="",
        absolute_expires_at=timezone.now() + timedelta(hours=1),
    )

    with pytest.raises(PermissionDenied):
        revoke_account_session(actor=user, account_session_id=session.pk)


def test_administrative_mfa_reset_is_scoped_audited_and_ends_target_sessions() -> None:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    target = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=target,
        role=ClinicMembership.Role.THERAPIST,
    )
    challenge = start_totp_enrollment(user=target)
    confirm_totp_enrollment(
        user=target,
        code=current_totp_code(secret=challenge.secret),
    )
    django_session = Session.objects.create(
        session_key="target-live-session",
        session_data="e30:synthetic",
        expire_date=timezone.now() + timedelta(hours=1),
    )
    tracked = AccountSession.objects.create_for_session(
        user=target,
        session_key=django_session.session_key,
        client_label="Navegador alvo",
        network_hint="",
        absolute_expires_at=timezone.now() + timedelta(hours=1),
    )

    administratively_reset_mfa(
        clinic_id=clinic.pk,
        actor=administrator,
        target_user=target,
        reason="Dispositivo perdido informado pelo titular.",
    )

    assert not UserMFA.objects.filter(user=target).exists()
    assert not MFARecoveryCode.objects.filter(user=target).exists()
    tracked.refresh_from_db()
    assert tracked.revoked_at is not None
    assert not Session.objects.filter(session_key=django_session.session_key).exists()
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        actor_id=administrator.pk,
        resource_type="user_mfa",
        resource_id=str(target.pk),
        outcome="success",
    ).exists()


def test_administrative_mfa_reset_denies_target_from_another_clinic() -> None:
    administrator_clinic = ClinicFactory.create()
    target_clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    target = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=administrator_clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    ClinicMembershipFactory.create(
        clinic=target_clinic,
        user=target,
        role=ClinicMembership.Role.THERAPIST,
    )

    with pytest.raises(PermissionDenied):
        administratively_reset_mfa(
            clinic_id=administrator_clinic.pk,
            actor=administrator,
            target_user=target,
            reason="Solicitação sintética.",
        )


def test_revoking_all_other_sessions_requires_current_password(client: Client) -> None:
    user, _clinic = authenticated_admin(client)
    other_django_session = Session.objects.create(
        session_key="reauth-other-session",
        session_data="e30:synthetic",
        expire_date=timezone.now() + timedelta(hours=1),
    )
    other = AccountSession.objects.create_for_session(
        user=user,
        session_key=other_django_session.session_key,
        client_label="Outro navegador",
        network_hint="",
        absolute_expires_at=timezone.now() + timedelta(hours=1),
    )

    denied = client.post(
        reverse("account_sessions"),
        {"action": "revoke_others", "password": "senha-incorreta"},
    )

    assert denied.status_code == 400
    other.refresh_from_db()
    assert other.revoked_at is None

    accepted = client.post(
        reverse("account_sessions"),
        {"action": "revoke_others", "password": "senha-sintetica-segura"},
    )

    assert accepted.status_code == 302
    other.refresh_from_db()
    assert other.revoked_at is not None


@override_settings(MFA_ENFORCEMENT_ENABLED=True)
def test_framework_staff_access_requires_mfa_without_clinic_role(
    client: Client,
) -> None:
    staff = UserFactory.create(is_staff=True)
    client.force_login(staff)

    response = client.get("/admin/")

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("mfa_enroll")


@override_settings(MFA_RATE_LIMIT_ATTEMPTS=2, MFA_RATE_LIMIT_WINDOW_SECONDS=300)
def test_totp_confirmation_and_verification_are_rate_limited() -> None:
    user = UserFactory.create()
    challenge = start_totp_enrollment(user=user)

    with pytest.raises(ValueError):
        confirm_totp_enrollment(user=user, code="000000")
    with pytest.raises(ValueError):
        confirm_totp_enrollment(user=user, code="000000")
    with pytest.raises(MFAAttemptRateLimitedError):
        confirm_totp_enrollment(
            user=user,
            code=current_totp_code(secret=challenge.secret),
        )

    verification_user = UserFactory.create()
    verification_challenge = start_totp_enrollment(user=verification_user)
    confirm_totp_enrollment(
        user=verification_user,
        code=current_totp_code(secret=verification_challenge.secret),
    )
    assert consume_mfa_code(user=verification_user, code="000000") is False
    assert consume_mfa_code(user=verification_user, code="000000") is False
    with pytest.raises(MFAAttemptRateLimitedError):
        consume_mfa_code(
            user=verification_user,
            code=current_totp_code(secret=verification_challenge.secret),
        )


@override_settings(MFA_RATE_LIMIT_ATTEMPTS=1, MFA_RATE_LIMIT_WINDOW_SECONDS=300)
def test_mfa_attempt_budget_is_reserved_before_code_validation() -> None:
    user = UserFactory.create()

    _mfa_rate_limit(user=user, scope="concurrent-reservation")
    with pytest.raises(MFAAttemptRateLimitedError):
        _mfa_rate_limit(user=user, scope="concurrent-reservation")


def test_django_admin_login_uses_account_entrypoint(client: Client) -> None:
    response = client.get("/admin/login/")

    assert response.status_code == 302
    assert response.headers["Location"] == (
        f"{reverse('account_login')}?next=%2Fadmin%2F"
    )


def test_global_staff_can_authenticate_through_account_entrypoint(
    client: Client,
) -> None:
    staff = User.objects.create_user(
        email="staff-global@example.test",
        password="senha-sintetica-segura",
        is_staff=True,
    )

    response = client.post(
        f"{reverse('account_login')}?next=/admin/",
        {
            "email": staff.email,
            "password": "senha-sintetica-segura",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/admin/"
    assert AccountSession.objects.filter(user=staff, revoked_at__isnull=True).exists()
    assert client.get("/admin/").status_code == 200


@override_settings(MFA_ENFORCEMENT_ENABLED=True)
def test_administrative_mfa_reset_requires_verified_actor_mfa(client: Client) -> None:
    administrator, clinic = authenticated_admin(client)
    target = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=target,
        role=ClinicMembership.Role.THERAPIST,
    )
    administrator_challenge = start_totp_enrollment(user=administrator)
    confirm_totp_enrollment(
        user=administrator,
        code=current_totp_code(secret=administrator_challenge.secret),
    )
    target_challenge = start_totp_enrollment(user=target)
    confirm_totp_enrollment(
        user=target,
        code=current_totp_code(secret=target_challenge.secret),
    )

    response = client.post(
        reverse("administrative_mfa_reset"),
        {
            "target_user_id": str(target.pk),
            "reason": "Dispositivo perdido.",
            "password": "senha-sintetica-segura",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("mfa_verify")
    assert UserMFA.objects.filter(user=target).exists()


def test_administrative_mfa_reset_http_flow_requires_current_password(
    client: Client,
) -> None:
    administrator, clinic = authenticated_admin(client)
    target = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=target,
        role=ClinicMembership.Role.THERAPIST,
    )
    challenge = start_totp_enrollment(user=target)
    confirm_totp_enrollment(
        user=target,
        code=current_totp_code(secret=challenge.secret),
    )

    denied = client.post(
        reverse("administrative_mfa_reset"),
        {
            "target_user_id": str(target.pk),
            "reason": "Dispositivo perdido.",
            "password": "senha-incorreta",
        },
    )
    assert denied.status_code == 400
    assert UserMFA.objects.filter(user=target).exists()

    reason = "Dispositivo perdido."
    accepted = client.post(
        reverse("administrative_mfa_reset"),
        {
            "target_user_id": str(target.pk),
            "reason": reason,
            "password": "senha-sintetica-segura",
        },
    )
    assert accepted.status_code == 302
    assert accepted.headers["Location"] == reverse("workspace_vertical")
    assert not UserMFA.objects.filter(user=target).exists()
    audit_event = AuditEvent.infrastructure_objects.get(
        clinic_id=clinic.pk,
        actor_id=administrator.pk,
        resource_type="user_mfa",
        resource_id=str(target.pk),
    )
    assert audit_event.justification_digest
    assert reason not in audit_event.justification_digest


def test_recovery_codes_response_is_not_cacheable(client: Client) -> None:
    user, _clinic = authenticated_admin(client)
    enrollment = client.get(reverse("mfa_enroll"))
    assert enrollment.status_code == 200
    secret = UserMFA.objects.get(user=user).decrypt_secret()

    response = client.post(
        reverse("mfa_enroll"),
        {"code": current_totp_code(secret=secret)},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    content = response.content.decode("utf-8")
    assert "Códigos de recuperação" in content
    assert "<title>Códigos de recuperação" in content


@override_settings(MFA_ENFORCEMENT_ENABLED=True)
def test_active_therapist_must_enroll_mfa_before_workspace(client: Client) -> None:
    therapist = UserFactory.create()
    clinic = ClinicFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=therapist,
        role=ClinicMembership.Role.THERAPIST,
    )
    client.force_login(therapist)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(reverse("workspace_vertical"))

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("mfa_enroll")


@override_settings(MFA_ENFORCEMENT_ENABLED=True)
def test_administrative_staff_must_enroll_mfa_before_workspace(
    client: Client,
) -> None:
    staff = UserFactory.create()
    clinic = ClinicFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=staff,
        role=ClinicMembership.Role.ADMINISTRATIVE_STAFF,
    )
    client.force_login(staff)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(reverse("workspace_vertical"))

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("mfa_enroll")


@override_settings(
    SENSITIVE_REAUTH_RATE_LIMIT_ATTEMPTS=2,
    SENSITIVE_REAUTH_RATE_LIMIT_WINDOW_SECONDS=300,
)
def test_sensitive_reauthentication_is_rate_limited_per_identity() -> None:
    actor = UserFactory.create()
    actor.set_password("senha-correta")
    actor.save(update_fields=("password", "credentials_changed_at"))

    assert reauthenticate_sensitive_action(actor=actor, password="errada") is False
    assert reauthenticate_sensitive_action(actor=actor, password="errada") is False
    with pytest.raises(SensitiveActionRateLimitedError):
        reauthenticate_sensitive_action(actor=actor, password="senha-correta")


@override_settings(
    SENSITIVE_REAUTH_RATE_LIMIT_ATTEMPTS=1,
    SENSITIVE_REAUTH_RATE_LIMIT_WINDOW_SECONDS=300,
)
def test_session_reauthentication_rate_limit_returns_429(client: Client) -> None:
    authenticated_admin(client)
    assert client.get(reverse("account_sessions")).status_code == 200
    payload = {"action": "revoke_others", "password": "senha-incorreta"}

    assert client.post(reverse("account_sessions"), payload).status_code == 400
    rate_limited = client.post(reverse("account_sessions"), payload)

    assert rate_limited.status_code == 429
    assert rate_limited.headers["Retry-After"] == "300"


@override_settings(MFA_ENFORCEMENT_ENABLED=True)
def test_admin_mfa_challenge_returns_to_original_admin_destination(
    client: Client,
) -> None:
    staff = User.objects.create_user(
        email="staff-mfa-next@example.test",
        password="senha-sintetica-segura",
        is_staff=True,
    )
    challenge = start_totp_enrollment(user=staff)
    confirm_totp_enrollment(
        user=staff,
        code=current_totp_code(secret=challenge.secret),
    )
    login_response = client.post(
        f"{reverse('account_login')}?next=/admin/",
        {"email": staff.email, "password": "senha-sintetica-segura"},
    )
    assert login_response.headers["Location"] == "/admin/"
    challenge_response = client.get("/admin/")
    assert challenge_response.headers["Location"] == reverse("mfa_verify")

    verified = client.post(
        reverse("mfa_verify"),
        {"code": current_totp_code(secret=challenge.secret)},
    )

    assert verified.status_code == 302
    assert verified.headers["Location"] == "/admin/"


@override_settings(MFA_ENFORCEMENT_ENABLED=True)
def test_initial_admin_mfa_enrollment_preserves_admin_destination(
    client: Client,
) -> None:
    staff = User.objects.create_user(
        email="staff-mfa-enrollment-next@example.test",
        password="senha-sintetica-segura",
        is_staff=True,
    )
    login_response = client.post(
        f"{reverse('account_login')}?next=/admin/",
        {"email": staff.email, "password": "senha-sintetica-segura"},
    )
    assert login_response.headers["Location"] == "/admin/"
    challenge_response = client.get("/admin/")
    assert challenge_response.headers["Location"] == reverse("mfa_enroll")
    client.get(reverse("mfa_enroll"))
    secret = UserMFA.objects.get(user=staff).decrypt_secret()

    enrolled = client.post(
        reverse("mfa_enroll"),
        {"code": current_totp_code(secret=secret)},
    )

    assert enrolled.status_code == 200
    assert enrolled.context["continue_url"] == "/admin/"
    assert b'href="/admin/"' in enrolled.content
    assert "mfa_next" not in client.session
