"""Authentication and password recovery acceptance tests for PRD 8.4.1."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.db.models import QuerySet
from django.test import Client, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import ClinicInvitation, User
from audit.models import AuditAction, AuditEvent, AuditOutcome
from clinics.models import Clinic, ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db

GENERIC_LOGIN_ERROR = "Não foi possível entrar com os dados informados."
GENERIC_RECOVERY_RESPONSE = (
    "Se existir uma conta ativa para este e-mail, você receberá as instruções."
)


def create_login_identity(
    *, email: str = "pessoa@example.test", password: str = "senha-segura-sintetica"
) -> tuple[User, Clinic]:
    """Create one credential with one currently authorized active tenant."""
    user = User.objects.create_user(email=email, password=password)
    clinic = ClinicFactory.create()
    ClinicMembershipFactory.create(
        user=user,
        clinic=clinic,
        role=ClinicMembership.Role.THERAPIST,
    )
    return user, clinic


def login_client(
    client: Client,
    *,
    email: str = "pessoa@example.test",
    password: str = "senha-segura-sintetica",
) -> None:
    """Authenticate through the public HTTP contract."""
    response = client.post(
        reverse("account_login"),
        {"email": email, "password": password},
    )
    assert response.status_code == 302


def extract_reset_path() -> str:
    """Return the local reset path from the latest synthetic e-mail."""
    match = re.search(
        r"https?://[^/]+(?P<path>/accounts/password-reset/\S+)",
        str(mail.outbox[-1].body),
    )
    assert match is not None
    return match.group("path")


def authenticate_clinic_admin(client: Client) -> tuple[User, Clinic]:
    """Create an authenticated administrator with an explicit active clinic."""
    actor = UserFactory.create()
    clinic = ClinicFactory.create()
    ClinicMembershipFactory.create(
        user=actor,
        clinic=clinic,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    client.force_login(actor)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()
    return actor, clinic


def test_login_uses_canonical_email_rotates_session_and_selects_active_tenant(
    client: Client,
) -> None:
    user, clinic = create_login_identity(email="pessoa@example.test")
    session = client.session
    session["anonymous_marker"] = "retained"
    session.save()
    previous_session_key = session.session_key

    response = client.post(
        reverse("account_login"),
        {
            "email": "  PESSOA@EXAMPLE.TEST  ",
            "password": "senha-segura-sintetica",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("workspace_vertical")
    assert client.session[SESSION_KEY] == str(user.pk)
    assert client.session["active_clinic_id"] == str(clinic.pk)
    assert client.session.session_key != previous_session_key
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(
            actor_id=user.pk,
            action=AuditAction.LOGIN,
            outcome=AuditOutcome.SUCCESS,
            resource_type="session",
        )
        .exists()
    )


def test_login_uses_same_generic_error_for_unknown_wrong_or_tenantless_identity(
    client: Client,
) -> None:
    create_login_identity()
    tenantless = User.objects.create_user(
        email="sem-clinica@example.test",
        password="senha-segura-sintetica",
    )
    assert tenantless.is_active is True

    responses = []
    for email, password in (
        ("unknown@example.test", "senha-segura-sintetica"),
        ("pessoa@example.test", "senha-incorreta-sintetica"),
        ("sem-clinica@example.test", "senha-segura-sintetica"),
    ):
        cache.clear()
        responses.append(
            client.post(
                reverse("account_login"),
                {"email": email, "password": password},
            )
        )

    for response in responses:
        assert response.status_code == 200
        assert GENERIC_LOGIN_ERROR in response.content.decode("utf-8")
        assert SESSION_KEY not in client.session


@override_settings(LOGIN_RATE_LIMIT_ATTEMPTS=2, LOGIN_RATE_LIMIT_WINDOW_SECONDS=90)
def test_login_rate_limit_is_configurable_and_non_enumerating(client: Client) -> None:
    cache.clear()
    payload = {"email": "unknown@example.test", "password": "senha-incorreta"}

    first = client.post(reverse("account_login"), payload)
    second = client.post(reverse("account_login"), payload)
    blocked = client.post(reverse("account_login"), payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "90"
    assert GENERIC_LOGIN_ERROR in blocked.content.decode("utf-8")


@override_settings(LOGIN_RATE_LIMIT_ATTEMPTS=2, LOGIN_RATE_LIMIT_WINDOW_SECONDS=90)
def test_login_rate_limit_cannot_be_bypassed_by_rotating_network_origin(
    client: Client,
) -> None:
    cache.clear()
    create_login_identity()

    for index in range(2):
        response = client.post(
            reverse("account_login"),
            {"email": "PROFISSIONAL@example.test", "password": "senha-incorreta"},
            REMOTE_ADDR=f"198.51.100.{index + 1}",
        )
        assert response.status_code == 200

    blocked = client.post(
        reverse("account_login"),
        {"email": "profissional@example.test", "password": "segredo-seguro"},
        REMOTE_ADDR="198.51.100.99",
    )

    assert blocked.status_code == 429
    assert SESSION_KEY not in client.session


def test_login_service_exposes_only_generic_rejection() -> None:
    from accounts.services import LoginRejectedError, login_user

    request = Client().request().wsgi_request
    with pytest.raises(LoginRejectedError, match=GENERIC_LOGIN_ERROR):
        login_user(
            request=request,
            email="unknown@example.test",
            password="senha-incorreta",
        )


def test_logout_is_post_only_flushes_session_and_is_audited(client: Client) -> None:
    user, clinic = create_login_identity()
    login_client(client)
    authenticated_session_key = client.session.session_key

    get_response = client.get(reverse("account_logout"))
    response = client.post(reverse("account_logout"))

    assert get_response.status_code == 405
    assert response.status_code == 302
    assert response.headers["Location"] == reverse("account_login")
    assert SESSION_KEY not in client.session
    assert client.session.session_key != authenticated_session_key
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(
            actor_id=user.pk,
            action=AuditAction.UPDATE,
            outcome=AuditOutcome.SUCCESS,
            resource_type="session",
        )
        .exists()
    )


def test_authentication_templates_are_accessible_and_pt_br(client: Client) -> None:
    for url_name, expected_heading in (
        ("account_login", "Entrar na plataforma"),
        ("password_recovery", "Recuperar acesso"),
    ):
        response = client.get(reverse(url_name))
        content = response.content.decode("utf-8")

        assert response.status_code == 200
        assert '<html lang="pt-BR">' in content
        assert 'href="#main-content"' in content
        assert '<main id="main-content"' in content
        assert expected_heading in content
        assert "<label" in content


def test_clinic_admin_issues_invitation_over_http_and_delivers_pt_br_email(
    client: Client,
) -> None:
    _actor, clinic = authenticate_clinic_admin(client)

    page = client.get(reverse("invitation_issue"))
    response = client.post(
        reverse("invitation_issue"),
        {
            "recipient_email": " Convidada@Example.TEST ",
            "initial_role": ClinicMembership.Role.THERAPIST,
            "expires_in_hours": "24",
        },
    )

    assert page.status_code == 200
    assert '<html lang="pt-BR">' in page.content.decode("utf-8")
    assert "Enviar convite" in page.content.decode("utf-8")
    assert response.status_code == 200
    assert "Convite enviado" in response.content.decode("utf-8")
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["convidada@example.test"]
    assert "Convite para acessar a clínica" in message.subject
    invitation = ClinicInvitation.objects.for_clinic(clinic.pk).get()
    assert invitation.token_digest not in message.body
    assert re.search(r"/accounts/invitations/[^/]+/accept/", str(message.body))


def test_new_recipient_accepts_http_invitation_and_creates_membership(
    client: Client,
) -> None:
    _actor, clinic = authenticate_clinic_admin(client)
    client.post(
        reverse("invitation_issue"),
        {
            "recipient_email": "nova-pessoa@example.test",
            "initial_role": ClinicMembership.Role.THERAPIST,
            "expires_in_hours": "24",
        },
    )
    match = re.search(
        r"(?P<path>/accounts/invitations/[^/]+/accept/)",
        str(mail.outbox[0].body),
    )
    assert match is not None
    accept_path = match.group("path")
    client.logout()

    page = client.get(accept_path)
    response = client.post(
        accept_path,
        {
            "first_name": "Pessoa",
            "last_name": "Convidada",
            "password": "senha-sintetica-longa-e-nao-reutilizavel",
            "confirm_password": "senha-sintetica-longa-e-nao-reutilizavel",
        },
    )

    assert page.status_code == 200
    assert "Aceitar convite" in page.content.decode("utf-8")
    assert response.status_code == 302
    assert response.headers["Location"] == reverse("account_login")
    recipient = User.objects.get(email="nova-pessoa@example.test")
    assert (
        ClinicMembership.objects.for_clinic(clinic.pk)
        .filter(
            user=recipient,
            role=ClinicMembership.Role.THERAPIST,
        )
        .exists()
    )


def test_existing_recipient_must_log_in_to_accept_http_invitation(
    client: Client,
) -> None:
    _actor, clinic = authenticate_clinic_admin(client)
    existing, first_clinic = create_login_identity(
        email="existente-http@example.test",
        password="senha-original-sintetica-segura",
    )
    client.post(
        reverse("invitation_issue"),
        {
            "recipient_email": existing.email,
            "initial_role": ClinicMembership.Role.THERAPIST,
            "expires_in_hours": "24",
        },
    )
    match = re.search(
        r"(?P<path>/accounts/invitations/[^/]+/accept/)",
        str(mail.outbox[0].body),
    )
    assert match is not None
    accept_path = match.group("path")
    client.logout()

    anonymous = client.post(accept_path, {})
    assert anonymous.status_code == 302
    assert anonymous.headers["Location"].startswith(reverse("account_login"))

    client.force_login(existing)
    accepted = client.post(accept_path, {})

    assert accepted.status_code == 302
    assert accepted.headers["Location"] == reverse("workspace_vertical")
    assert client.session["active_clinic_id"] == str(clinic.pk)
    existing.refresh_from_db()
    assert existing.check_password("senha-original-sintetica-segura")
    assert (
        ClinicMembership.objects.for_clinic(first_clinic.pk)
        .filter(user=existing)
        .count()
        == 1
    )
    assert (
        ClinicMembership.objects.for_clinic(clinic.pk).filter(user=existing).count()
        == 1
    )


def test_clinic_admin_revokes_invitation_over_post_only_http(client: Client) -> None:
    _actor, clinic = authenticate_clinic_admin(client)
    client.post(
        reverse("invitation_issue"),
        {
            "recipient_email": "revogada@example.test",
            "initial_role": ClinicMembership.Role.THERAPIST,
            "expires_in_hours": "24",
        },
    )
    invitation = ClinicInvitation.objects.for_clinic(clinic.pk).get()

    get_response = client.get(
        reverse("invitation_revoke", kwargs={"invitation_id": invitation.pk})
    )
    response = client.post(
        reverse("invitation_revoke", kwargs={"invitation_id": invitation.pk})
    )

    assert get_response.status_code == 405
    assert response.status_code == 302
    assert response.headers["Location"] == reverse("invitation_issue")
    invitation.refresh_from_db()
    assert invitation.revoked_at is not None


def test_password_recovery_response_is_generic_for_known_and_unknown_email(
    client: Client,
) -> None:
    create_login_identity()

    known = client.post(
        reverse("password_recovery"), {"email": " PESSOA@EXAMPLE.TEST "}
    )
    known_content = known.content.decode("utf-8")
    assert len(mail.outbox) == 1

    unknown = client.post(
        reverse("password_recovery"), {"email": "unknown@example.test"}
    )
    unknown_content = unknown.content.decode("utf-8")

    assert known.status_code == unknown.status_code == 200
    assert GENERIC_RECOVERY_RESPONSE in known_content
    assert GENERIC_RECOVERY_RESPONSE in unknown_content
    assert len(mail.outbox) == 1


@override_settings(
    PASSWORD_RECOVERY_RATE_LIMIT_ATTEMPTS=1,
    PASSWORD_RECOVERY_RATE_LIMIT_WINDOW_SECONDS=120,
)
def test_password_recovery_rate_limit_is_configurable(client: Client) -> None:
    cache.clear()
    payload = {"email": "unknown@example.test"}

    allowed = client.post(reverse("password_recovery"), payload)
    blocked = client.post(reverse("password_recovery"), payload)

    assert allowed.status_code == 200
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "120"
    assert GENERIC_RECOVERY_RESPONSE in blocked.content.decode("utf-8")


@override_settings(
    PASSWORD_RECOVERY_RATE_LIMIT_ATTEMPTS=2,
    PASSWORD_RECOVERY_RATE_LIMIT_WINDOW_SECONDS=120,
)
def test_password_recovery_rate_limit_cannot_be_bypassed_by_rotating_origin(
    client: Client,
) -> None:
    cache.clear()

    for index in range(2):
        response = client.post(
            reverse("password_recovery"),
            {"email": " PESSOA@EXAMPLE.TEST "},
            REMOTE_ADDR=f"198.51.100.{index + 1}",
        )
        assert response.status_code == 200

    blocked = client.post(
        reverse("password_recovery"),
        {"email": "pessoa@example.test"},
        REMOTE_ADDR="198.51.100.99",
    )

    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "120"


def test_password_reset_is_single_use_and_invalidates_all_existing_sessions(
    client: Client,
) -> None:
    user, _clinic = create_login_identity()
    other_client = Client()
    login_client(client)
    login_client(other_client)
    previous_credentials_changed_at = user.credentials_changed_at

    recovery_client = Client()
    recovery_client.post(reverse("password_recovery"), {"email": user.email})
    reset_path = extract_reset_path()
    form_response = recovery_client.get(reset_path)
    reset_response = recovery_client.post(
        reset_path,
        {
            "new_password": "nova-senha-sintetica-segura",
            "confirm_password": "nova-senha-sintetica-segura",
        },
    )

    assert form_response.status_code == 200
    assert reset_response.status_code == 302
    assert reset_response.headers["Location"] == reverse("password_reset_complete")
    user.refresh_from_db()
    assert user.check_password("nova-senha-sintetica-segura")
    assert user.credentials_changed_at > previous_credentials_changed_at

    assert client.get(reverse("home")).status_code == 200
    assert other_client.get(reverse("home")).status_code == 200
    assert SESSION_KEY not in client.session
    assert SESSION_KEY not in other_client.session

    reused = recovery_client.post(
        reset_path,
        {
            "new_password": "terceira-senha-sintetica-segura",
            "confirm_password": "terceira-senha-sintetica-segura",
        },
    )
    assert reused.status_code == 400
    assert "Link inválido ou expirado." in reused.content.decode("utf-8")


@override_settings(PASSWORD_RESET_TIMEOUT=60)
def test_password_reset_service_rejects_expired_token() -> None:
    from accounts.services import reset_password

    user, _clinic = create_login_identity()
    issued_at = datetime(2026, 9, 1, 12, 0, 0)
    with patch.object(default_token_generator, "_now", return_value=issued_at):
        token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))

    with patch.object(
        default_token_generator,
        "_now",
        return_value=issued_at + timedelta(seconds=61),
    ):
        accepted = reset_password(
            uid=uid,
            token=token,
            new_password="nova-senha-sintetica-segura",
        )

    assert accepted is False
    user.refresh_from_db()
    assert user.check_password("senha-segura-sintetica")


def test_password_reset_locks_identity_before_validating_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from accounts.services import reset_password

    user, _clinic = create_login_identity()
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    calls: list[str] = []
    original_select_for_update = User.objects.select_for_update
    original_check_token = default_token_generator.check_token

    def tracked_select_for_update(
        nowait: bool = False,
        skip_locked: bool = False,
        of: Sequence[str] = (),
        no_key: bool = False,
    ) -> QuerySet[User]:
        calls.append("lock")
        return original_select_for_update(
            nowait=nowait,
            skip_locked=skip_locked,
            of=of,
            no_key=no_key,
        )

    def tracked_check_token(user: User, token: str) -> bool:
        calls.append("check")
        return bool(original_check_token(user, token))

    monkeypatch.setattr(User.objects, "select_for_update", tracked_select_for_update)
    monkeypatch.setattr(default_token_generator, "check_token", tracked_check_token)

    assert reset_password(
        uid=uid,
        token=token,
        new_password="nova-senha-sintetica-segura",
    )
    assert calls[:2] == ["lock", "check"]
