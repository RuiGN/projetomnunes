"""Identity model security acceptance tests."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.utils import timezone

from accounts.models import ClinicInvitation, User, UserManager
from accounts.services import accept_invitation, issue_invitation, revoke_invitation
from clinics.models import ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.mark.django_db
def test_user_authenticates_by_canonical_email_without_global_role() -> None:
    user = User.objects.create_user(
        email="  Pessoa.TESTE@Example.TEST  ",
        password="senha-sintetica-nao-reutilizavel",
        first_name="Pessoa",
        last_name="Sintética",
    )

    assert user.email == "pessoa.teste@example.test"
    assert User.USERNAME_FIELD == "email"
    assert user.username == ""
    assert user.is_active is True
    assert user.is_staff is False
    assert user.is_superuser is False
    assert not hasattr(user, "role")
    assert user.security_state_changed_at is not None
    assert user.credentials_changed_at is not None


@pytest.mark.django_db
def test_user_email_is_unique_case_insensitively() -> None:
    User.objects.create_user(
        email="pessoa@example.test",
        password="senha-sintetica-nao-reutilizavel",
    )

    with pytest.raises(IntegrityError):
        User.objects.create_user(
            email="PESSOA@EXAMPLE.TEST",
            password="outra-senha-sintetica-nao-reutilizavel",
        )


@pytest.mark.django_db
def test_user_requires_email() -> None:
    with pytest.raises(ValueError, match="email"):
        User.objects.create_user(email="", password="senha-sintetica")


@pytest.mark.django_db
def test_clinic_admin_issues_and_recipient_accepts_single_use_invitation() -> None:
    clinic = ClinicFactory.create()
    issuer = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=issuer,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )

    issued = issue_invitation(
        clinic_id=clinic.id,
        issuer=issuer,
        recipient_email=" Convidada@Example.TEST ",
        initial_role=ClinicMembership.Role.THERAPIST,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    assert issued.invitation.recipient_email == "convidada@example.test"
    assert issued.raw_token not in issued.invitation.token_digest
    assert issued.invitation.used_at is None
    invited_user = accept_invitation(
        raw_token=issued.raw_token,
        password="senha-sintetica-longa-e-nao-reutilizavel",
        first_name="Pessoa",
        last_name="Convidada",
    )
    membership = ClinicMembership.objects.for_clinic(clinic.id).get(user=invited_user)
    assert membership.role == ClinicMembership.Role.THERAPIST
    issued.invitation.refresh_from_db()
    assert issued.invitation.used_at is not None

    with pytest.raises(ValueError, match="inválido ou expirado"):
        accept_invitation(
            raw_token=issued.raw_token,
            password="outra-senha-sintetica-longa",
            first_name="Outro",
            last_name="Nome",
        )


@pytest.mark.django_db
def test_invitation_requires_active_admin_in_same_clinic() -> None:
    clinic = ClinicFactory.create()
    other_clinic = ClinicFactory.create()
    issuer = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=other_clinic,
        user=issuer,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )

    with pytest.raises(PermissionDenied):
        issue_invitation(
            clinic_id=clinic.id,
            issuer=issuer,
            recipient_email="pessoa@example.test",
            initial_role=ClinicMembership.Role.THERAPIST,
            expires_at=timezone.now() + timedelta(hours=24),
        )


@pytest.mark.django_db
def test_invitation_can_be_revoked_once_and_never_stores_raw_token() -> None:
    clinic = ClinicFactory.create()
    issuer = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=issuer,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    issued = issue_invitation(
        clinic_id=clinic.id,
        issuer=issuer,
        recipient_email="pessoa@example.test",
        initial_role=ClinicMembership.Role.THERAPIST,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    revoke_invitation(
        clinic_id=clinic.id,
        invitation_id=issued.invitation.id,
        actor=issuer,
    )
    issued.invitation.refresh_from_db()
    assert issued.invitation.revoked_at is not None
    assert not ClinicInvitation.infrastructure_objects.filter(
        token_digest=issued.raw_token
    ).exists()

    with pytest.raises(ValueError, match="inválido ou expirado"):
        accept_invitation(
            raw_token=issued.raw_token,
            password="senha-sintetica-longa-e-nao-reutilizavel",
            first_name="Pessoa",
            last_name="Convidada",
        )


@pytest.mark.django_db
def test_invitation_acceptance_validates_password_before_consuming_token() -> None:
    clinic = ClinicFactory.create()
    issuer = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=issuer,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    issued = issue_invitation(
        clinic_id=clinic.id,
        issuer=issuer,
        recipient_email="senha-fraca@example.test",
        initial_role=ClinicMembership.Role.THERAPIST,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    with pytest.raises(
        ValidationError,
        match="curta|short|comum|common|numérica|numeric",
    ):
        accept_invitation(
            raw_token=issued.raw_token,
            password="123",
            first_name="Pessoa",
            last_name="Convidada",
        )

    issued.invitation.refresh_from_db()
    assert issued.invitation.used_at is None
    assert not User.objects.filter(email="senha-fraca@example.test").exists()


@pytest.mark.django_db
def test_invitation_duplicate_race_uses_generic_error_and_keeps_token_unused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clinic = ClinicFactory.create()
    issuer = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=issuer,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    issued = issue_invitation(
        clinic_id=clinic.id,
        issuer=issuer,
        recipient_email="corrida@example.test",
        initial_role=ClinicMembership.Role.THERAPIST,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    def raise_duplicate(*args: object, **kwargs: object) -> User:
        del args, kwargs
        raise IntegrityError("synthetic duplicate")

    monkeypatch.setattr(UserManager, "create_user", raise_duplicate)

    with pytest.raises(ValueError, match="inválido ou expirado"):
        accept_invitation(
            raw_token=issued.raw_token,
            password="senha-sintetica-longa-e-nao-reutilizavel",
            first_name="Pessoa",
            last_name="Convidada",
        )

    issued.invitation.refresh_from_db()
    assert issued.invitation.used_at is None


@pytest.mark.django_db
def test_existing_identity_accepts_second_clinic_only_as_itself() -> None:
    first_clinic = ClinicFactory.create()
    second_clinic = ClinicFactory.create()
    issuer = UserFactory.create()
    existing = User.objects.create_user(
        email="existente@example.test",
        password="senha-original-sintetica-segura",
        first_name="Nome",
        last_name="Preservado",
        preferred_layout=User.Layout.DETACHED,
    )
    ClinicMembershipFactory.create(clinic=first_clinic, user=existing)
    ClinicMembershipFactory.create(
        clinic=second_clinic,
        user=issuer,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    issued = issue_invitation(
        clinic_id=second_clinic.id,
        issuer=issuer,
        recipient_email="EXISTENTE@example.test",
        initial_role=ClinicMembership.Role.THERAPIST,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    with pytest.raises(PermissionDenied):
        accept_invitation(
            raw_token=issued.raw_token,
            actor=None,
            password="senha-hostil-sintetica-segura",
            first_name="Nome alterado",
            last_name="Perfil alterado",
        )

    accepted = accept_invitation(
        raw_token=issued.raw_token,
        actor=existing,
        password="senha-hostil-sintetica-segura",
        first_name="Nome alterado",
        last_name="Perfil alterado",
    )

    existing.refresh_from_db()
    assert accepted.pk == existing.pk
    assert existing.check_password("senha-original-sintetica-segura")
    assert (existing.first_name, existing.last_name) == ("Nome", "Preservado")
    assert existing.preferred_layout == User.Layout.DETACHED
    assert (
        ClinicMembership.objects.for_clinic(second_clinic.id)
        .filter(user=existing)
        .count()
        == 1
    )


@pytest.mark.django_db
def test_existing_identity_invitation_rejects_different_authenticated_actor() -> None:
    clinic = ClinicFactory.create()
    issuer = UserFactory.create()
    existing = User.objects.create_user(
        email="existente@example.test",
        password="senha-original-sintetica-segura",
    )
    attacker = User.objects.create_user(
        email="outra-pessoa@example.test",
        password="senha-atacante-sintetica-segura",
    )
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=issuer,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    issued = issue_invitation(
        clinic_id=clinic.id,
        issuer=issuer,
        recipient_email=existing.email,
        initial_role=ClinicMembership.Role.THERAPIST,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    with pytest.raises(PermissionDenied):
        accept_invitation(
            raw_token=issued.raw_token,
            actor=attacker,
            password="senha-hostil-sintetica-segura",
            first_name="",
            last_name="",
        )

    assert (
        not ClinicMembership.objects.for_clinic(clinic.id)
        .filter(user=existing)
        .exists()
    )


@pytest.mark.django_db
def test_existing_membership_is_not_duplicated_when_invitation_is_accepted() -> None:
    clinic = ClinicFactory.create()
    issuer = UserFactory.create()
    existing = User.objects.create_user(
        email="membro@example.test",
        password="senha-original-sintetica-segura",
    )
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=issuer,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    ClinicMembershipFactory.create(clinic=clinic, user=existing)
    issued = issue_invitation(
        clinic_id=clinic.id,
        issuer=issuer,
        recipient_email=existing.email,
        initial_role=ClinicMembership.Role.THERAPIST,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    accepted = accept_invitation(
        raw_token=issued.raw_token,
        actor=existing,
        password="",
        first_name="",
        last_name="",
    )

    assert accepted.pk == existing.pk
    assert (
        ClinicMembership.objects.for_clinic(clinic.id).filter(user=existing).count()
        == 1
    )
    issued.invitation.refresh_from_db()
    assert issued.invitation.used_at is not None


@pytest.mark.django_db
def test_invitation_reactivates_historical_membership_with_invited_role() -> None:
    clinic = ClinicFactory.create()
    issuer = UserFactory.create()
    existing = User.objects.create_user(
        email="membro-inativo@example.test",
        password="senha-original-sintetica-segura",
    )
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=issuer,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    membership = ClinicMembershipFactory.create(
        clinic=clinic,
        user=existing,
        role=ClinicMembership.Role.PATIENT,
        is_active=False,
        valid_from=timezone.localdate() - timedelta(days=30),
        valid_until=timezone.localdate() - timedelta(days=1),
    )
    issued = issue_invitation(
        clinic_id=clinic.id,
        issuer=issuer,
        recipient_email=existing.email,
        initial_role=ClinicMembership.Role.THERAPIST,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    accepted = accept_invitation(
        raw_token=issued.raw_token,
        actor=existing,
        password="",
        first_name="",
        last_name="",
    )

    membership.refresh_from_db()
    issued.invitation.refresh_from_db()
    assert accepted.pk == existing.pk
    assert membership.is_active is True
    assert membership.role == ClinicMembership.Role.THERAPIST
    assert membership.valid_from == timezone.localdate()
    assert membership.valid_until is None
    assert issued.invitation.used_at is not None
