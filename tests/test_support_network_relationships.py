"""Tests for support network invitations and permissions (8.16.1)."""

from typing import Any

import pytest
from django.core.exceptions import PermissionDenied

from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from support_network.contracts import InvitationStatus, SupportPermissionScope
from support_network.policies import (
    can_supporter_access_scope,
)
from support_network.services import (
    accept_support_invitation,
    create_support_invitation,
    decline_support_invitation,
    revoke_support_invitation,
    revoke_support_relationship,
    update_support_permissions,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic_fixture(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Apoio")


@pytest.fixture
def other_clinic_fixture(db: Any) -> Clinic:
    return ClinicFactory.create(name="Outra Clínica")


@pytest.fixture
def patient_user(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="paciente@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def supporter_user(clinic_fixture: Clinic) -> Any:
    return UserFactory.create(email="apoiador@exemplo.com")


@pytest.fixture
def patient_profile(
    db: Any, clinic_fixture: Clinic, patient_user: Any
) -> PatientProfile:
    return PatientProfile.infrastructure_objects.create(
        clinic=clinic_fixture,
        user=patient_user,
        full_name="Paciente Um",
        birth_date="1990-01-01",
    )


@pytest.mark.django_db
def test_create_support_invitation_with_valid_scopes(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
    patient_user: Any,
) -> None:
    invitation = create_support_invitation(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        invitee_name="Maria Apoio",
        invitee_email="maria@exemplo.com",
        permissions_offered=[
            SupportPermissionScope.VIEW_WELLNESS_SUMMARY.value,
            SupportPermissionScope.RECEIVE_URGENT_ALERTS.value,
        ],
        invited_by=patient_user,
    )

    assert invitation.status == InvitationStatus.PENDING.value
    assert invitation.invitee_email == "maria@exemplo.com"
    assert len(invitation.permissions_offered) == 2
    assert not invitation.is_expired()


@pytest.mark.django_db
def test_create_support_invitation_strictly_rejects_clinical_scopes(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
    patient_user: Any,
) -> None:
    """Clinical records, notes, prescriptions are strictly forbidden for supporters."""
    with pytest.raises(
        ValueError, match="não pode ser compartilhada com rede de apoio"
    ):
        create_support_invitation(
            clinic_id=clinic_fixture.id,
            patient_profile_id=patient_profile.id,
            invitee_name="Maria",
            invitee_email="maria@exemplo.com",
            permissions_offered=["medical_records"],
            invited_by=patient_user,
        )

    with pytest.raises(
        ValueError, match="não pode ser compartilhada com rede de apoio"
    ):
        create_support_invitation(
            clinic_id=clinic_fixture.id,
            patient_profile_id=patient_profile.id,
            invitee_name="Maria",
            invitee_email="maria@exemplo.com",
            permissions_offered=["clinical_messages"],
            invited_by=patient_user,
        )


@pytest.mark.django_db
def test_accept_invitation_creates_relationship_and_permissions(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
    patient_user: Any,
    supporter_user: Any,
) -> None:
    invitation = create_support_invitation(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        invitee_name="Amigo Apoiador",
        invitee_email=supporter_user.email,
        permissions_offered=[SupportPermissionScope.VIEW_WELLNESS_SUMMARY.value],
        invited_by=patient_user,
    )

    rel = accept_support_invitation(
        clinic_id=clinic_fixture.id,
        invitation_token=invitation.invitation_token,
        supporter_user=supporter_user,
    )

    invitation.refresh_from_db()
    assert invitation.status == InvitationStatus.ACCEPTED.value
    assert rel.is_active is True
    assert rel.supporter_user == supporter_user

    # Supporter can access granted scope
    assert can_supporter_access_scope(
        user=supporter_user,
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        requested_scope=SupportPermissionScope.VIEW_WELLNESS_SUMMARY.value,
    )

    # Supporter CANNOT access forbidden clinical scopes under any circumstances
    assert not can_supporter_access_scope(
        user=supporter_user,
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        requested_scope="medical_records",
    )


@pytest.mark.django_db
def test_expired_invitation_cannot_be_accepted(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
    patient_user: Any,
    supporter_user: Any,
) -> None:
    invitation = create_support_invitation(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        invitee_name="Amigo",
        invitee_email=supporter_user.email,
        expiry_days=-1,  # Expired in the past
        invited_by=patient_user,
    )

    with pytest.raises(ValueError, match="Convite expirado"):
        accept_support_invitation(
            clinic_id=clinic_fixture.id,
            invitation_token=invitation.invitation_token,
            supporter_user=supporter_user,
        )


@pytest.mark.django_db
def test_decline_and_revoke_invitation(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
    patient_user: Any,
) -> None:
    inv1 = create_support_invitation(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        invitee_name="Amigo 1",
        invitee_email="amigo1@exemplo.com",
        invited_by=patient_user,
    )
    declined = decline_support_invitation(
        clinic_id=clinic_fixture.id,
        invitation_token=inv1.invitation_token,
    )
    assert declined.status == InvitationStatus.DECLINED.value

    inv2 = create_support_invitation(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        invitee_name="Amigo 2",
        invitee_email="amigo2@exemplo.com",
        invited_by=patient_user,
    )
    revoked = revoke_support_invitation(
        clinic_id=clinic_fixture.id,
        invitation_id=inv2.id,
        revoked_by=patient_user,
    )
    assert revoked.status == InvitationStatus.REVOKED.value


@pytest.mark.django_db
def test_revoke_support_relationship_cleans_active_permissions(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
    patient_user: Any,
    supporter_user: Any,
) -> None:
    inv = create_support_invitation(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        invitee_name="Amigo",
        invitee_email=supporter_user.email,
        permissions_offered=[SupportPermissionScope.VIEW_WELLNESS_SUMMARY.value],
        invited_by=patient_user,
    )
    rel = accept_support_invitation(
        clinic_id=clinic_fixture.id,
        invitation_token=inv.invitation_token,
        supporter_user=supporter_user,
    )

    assert rel.is_active is True
    # Revoke
    revoked_rel = revoke_support_relationship(
        clinic_id=clinic_fixture.id,
        relationship_id=rel.id,
        revoked_by=patient_user,
    )
    assert revoked_rel.is_active is False
    assert not can_supporter_access_scope(
        user=supporter_user,
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        requested_scope=SupportPermissionScope.VIEW_WELLNESS_SUMMARY.value,
    )


@pytest.mark.django_db
def test_update_permissions_requires_step_up_auth(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
    patient_user: Any,
    supporter_user: Any,
) -> None:
    """PRD requirement: Step-up authentication required for changing permissions."""
    inv = create_support_invitation(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        invitee_name="Amigo",
        invitee_email=supporter_user.email,
        permissions_offered=[SupportPermissionScope.VIEW_WELLNESS_SUMMARY.value],
        invited_by=patient_user,
    )
    rel = accept_support_invitation(
        clinic_id=clinic_fixture.id,
        invitation_token=inv.invitation_token,
        supporter_user=supporter_user,
    )

    # Attempt without step-up auth -> PermissionDenied
    with pytest.raises(PermissionDenied, match="confirmação reforçada"):
        update_support_permissions(
            clinic_id=clinic_fixture.id,
            relationship_id=rel.id,
            granted_scopes={SupportPermissionScope.RECEIVE_URGENT_ALERTS.value},
            user=patient_user,
            step_up_authenticated=False,
        )

    # With step-up auth -> Success
    updated = update_support_permissions(
        clinic_id=clinic_fixture.id,
        relationship_id=rel.id,
        granted_scopes={SupportPermissionScope.RECEIVE_URGENT_ALERTS.value},
        user=patient_user,
        step_up_authenticated=True,
    )
    assert len(updated) == 1
    assert (
        updated[0].permission_scope
        == SupportPermissionScope.RECEIVE_URGENT_ALERTS.value
    )


@pytest.mark.django_db
def test_multi_tenant_isolation_prevents_cross_clinic_access(
    clinic_fixture: Clinic,
    other_clinic_fixture: Clinic,
    patient_profile: PatientProfile,
    patient_user: Any,
    supporter_user: Any,
) -> None:
    inv = create_support_invitation(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        invitee_name="Amigo",
        invitee_email=supporter_user.email,
        invited_by=patient_user,
    )

    # Cannot accept using other clinic's ID
    with pytest.raises(ValueError, match="Convite não encontrado"):
        accept_support_invitation(
            clinic_id=other_clinic_fixture.id,
            invitation_token=inv.invitation_token,
            supporter_user=supporter_user,
        )
