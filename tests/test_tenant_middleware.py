"""Authenticated request tenant resolution and middleware tests."""

from datetime import date, timedelta
from uuid import UUID

import pytest
from django.http import HttpResponse
from django.test import Client, RequestFactory, override_settings
from django.urls import path

from accounts.models import User
from clinics.middleware import is_tenant_exempt_path
from clinics.models import Clinic, ClinicMembership
from clinics.services import UnauthorizedClinicError, resolve_request_clinic
from clinics.typing import ClinicRequest

pytestmark = pytest.mark.django_db


def tenant_echo(request: ClinicRequest) -> HttpResponse:
    """Expose the resolved clinic ID for middleware integration assertions."""
    value = str(request.clinic.pk) if request.clinic is not None else "none"
    return HttpResponse(value)


urlpatterns = [path("tenant/", tenant_echo)]


def create_user(*, username: str = "therapist") -> User:
    """Create an authenticatable minimal user."""
    return User.objects.create_user(email=f"{username}@example.test")


def create_clinic(*, slug: str, is_active: bool = True) -> Clinic:
    """Create an infrastructure-visible clinic."""
    return Clinic.infrastructure_objects.create(
        name=f"Clínica {slug}",
        slug=slug,
        is_active=is_active,
    )


def create_membership(
    *,
    user: User,
    clinic: Clinic,
    is_active: bool = True,
    valid_from: date | None = None,
    valid_until: date | None = None,
) -> ClinicMembership:
    """Create a dated membership through its restricted infrastructure path."""
    return ClinicMembership.infrastructure_objects.create(
        user=user,
        clinic=clinic,
        role="therapist",
        is_active=is_active,
        valid_from=valid_from or date.today(),
        valid_until=valid_until,
    )


@override_settings(ROOT_URLCONF=__name__)
def test_anonymous_request_remains_compatible_with_public_and_login_routes(
    client: Client,
) -> None:
    """Anonymous requests bypass tenant resolution and receive a null context."""
    response = client.get("/tenant/")

    assert response.status_code == 200
    assert response.content == b"none"


@override_settings(ROOT_URLCONF=__name__)
def test_authenticated_header_selection_resolves_active_membership(
    client: Client,
) -> None:
    """A trusted request clinic comes from a valid UUID plus active membership."""
    user = create_user()
    clinic = create_clinic(slug="header")
    create_membership(user=user, clinic=clinic)
    client.force_login(user)

    response = client.get("/tenant/", headers={"X-Clinic-ID": str(clinic.pk)})

    assert response.status_code == 200
    assert response.content.decode() == str(clinic.pk)


@override_settings(ROOT_URLCONF=__name__)
def test_authenticated_explicit_session_selection_resolves_membership(
    client: Client,
) -> None:
    """A previously explicit session selection is reauthorized on every request."""
    user = create_user()
    clinic = create_clinic(slug="session")
    create_membership(user=user, clinic=clinic)
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get("/tenant/")

    assert response.status_code == 200
    assert response.content.decode() == str(clinic.pk)


@override_settings(ROOT_URLCONF=__name__)
def test_missing_selection_is_rejected_for_authenticated_request(
    client: Client,
) -> None:
    """Authenticated tenant-scoped requests cannot continue without a clinic."""
    client.force_login(create_user())

    response = client.get("/tenant/")

    assert response.status_code == 400
    assert response.json() == {"detail": "Selecione uma clínica para continuar."}


@pytest.mark.parametrize("selector", ["not-a-uuid", "", "123"])
@override_settings(ROOT_URLCONF=__name__)
def test_invalid_header_selection_is_rejected(client: Client, selector: str) -> None:
    """Malformed untrusted selectors never reach an unrestricted clinic lookup."""
    client.force_login(create_user())

    response = client.get("/tenant/", headers={"X-Clinic-ID": selector})

    assert response.status_code == 400
    assert response.json() == {"detail": "Identificador de clínica inválido."}


@override_settings(ROOT_URLCONF=__name__)
def test_header_takes_precedence_over_session_and_is_reauthorized(
    client: Client,
) -> None:
    """A session cannot make an unauthorized header selection acceptable."""
    user = create_user()
    allowed = create_clinic(slug="allowed")
    denied = create_clinic(slug="denied")
    create_membership(user=user, clinic=allowed)
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(allowed.pk)
    session.save()

    response = client.get("/tenant/", headers={"X-Clinic-ID": str(denied.pk)})

    assert response.status_code == 403
    assert response.json() == {"detail": "Acesso à clínica não autorizado."}


@override_settings(ROOT_URLCONF=__name__)
def test_other_tenant_selection_is_rejected_without_enumeration(client: Client) -> None:
    """A valid clinic UUID is still untrusted without the actor's membership."""
    actor = create_user(username="actor")
    other = create_user(username="other")
    clinic = create_clinic(slug="other")
    create_membership(user=other, clinic=clinic)
    client.force_login(actor)

    response = client.get("/tenant/", headers={"X-Clinic-ID": str(clinic.pk)})

    assert response.status_code == 403
    assert response.json() == {"detail": "Acesso à clínica não autorizado."}


@override_settings(ROOT_URLCONF=__name__)
def test_inactive_clinic_is_rejected(client: Client) -> None:
    """Membership does not authorize an inactive tenant root."""
    user = create_user()
    clinic = create_clinic(slug="inactive-clinic", is_active=False)
    create_membership(user=user, clinic=clinic)
    client.force_login(user)

    response = client.get("/tenant/", headers={"X-Clinic-ID": str(clinic.pk)})

    assert response.status_code == 403
    assert response.json() == {"detail": "Acesso à clínica não autorizado."}


def test_inactive_actor_cannot_resolve_request_clinic() -> None:
    """Direct tenant resolution rejects an inactive actor with active membership."""
    user = create_user(username="inactive-resolver")
    clinic = create_clinic(slug="inactive-resolver")
    create_membership(user=user, clinic=clinic)
    user.is_active = False
    user.save(update_fields=("is_active",))
    request = RequestFactory().get("/tenant/", headers={"X-Clinic-ID": str(clinic.pk)})

    with pytest.raises(UnauthorizedClinicError):
        resolve_request_clinic(request, user)


def test_stale_deactivated_actor_cannot_resolve_request_clinic() -> None:
    """Direct tenant resolution rechecks a stale actor against the user table."""
    user = create_user(username="stale-inactive-resolver")
    clinic = create_clinic(slug="stale-inactive-resolver")
    create_membership(user=user, clinic=clinic)
    User.objects.filter(pk=user.pk).update(is_active=False)
    request = RequestFactory().get("/tenant/", headers={"X-Clinic-ID": str(clinic.pk)})

    assert user.is_active is True
    with pytest.raises(UnauthorizedClinicError):
        resolve_request_clinic(request, user)


def test_stale_deleted_actor_cannot_resolve_clinic_or_change_target() -> None:
    """Tenant resolution denies a deleted stale actor without changing target data."""
    user = create_user(username="stale-deleted-resolver")
    clinic = create_clinic(slug="stale-deleted-resolver")
    create_membership(user=user, clinic=clinic)
    target = create_membership(
        user=create_user(username="stale-deleted-resolver-target"),
        clinic=clinic,
    )
    expected_updated_at = target.updated_at
    User.objects.filter(pk=user.pk).delete()
    request = RequestFactory().get("/tenant/", headers={"X-Clinic-ID": str(clinic.pk)})

    assert user.pk is not None
    with pytest.raises(UnauthorizedClinicError):
        resolve_request_clinic(request, user)

    target.refresh_from_db()
    assert target.role == "therapist"
    assert target.updated_at == expected_updated_at


@pytest.mark.parametrize(
    ("is_active", "valid_from", "valid_until"),
    [
        (False, date.today(), None),
        (True, date.today() - timedelta(days=2), date.today() - timedelta(days=1)),
        (True, date.today() + timedelta(days=1), None),
    ],
)
@override_settings(ROOT_URLCONF=__name__)
def test_inactive_expired_or_future_membership_is_rejected(
    client: Client,
    is_active: bool,
    valid_from: date,
    valid_until: date | None,
) -> None:
    """Only a currently valid active membership authorizes tenant resolution."""
    user = create_user()
    clinic = create_clinic(slug=f"validity-{str(is_active).lower()}-{valid_from}")
    create_membership(
        user=user,
        clinic=clinic,
        is_active=is_active,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    client.force_login(user)

    response = client.get("/tenant/", headers={"X-Clinic-ID": str(clinic.pk)})

    assert response.status_code == 403
    assert response.json() == {"detail": "Acesso à clínica não autorizado."}


def test_only_documented_infrastructure_paths_are_exempt() -> None:
    """The path exemption is narrow rather than a broad authentication bypass."""
    assert is_tenant_exempt_path("/admin/") is True
    assert is_tenant_exempt_path("/admin/login/") is True
    assert is_tenant_exempt_path("/tenant/") is False
    assert is_tenant_exempt_path("/administrator/") is False


def test_selector_ids_are_uuid_values() -> None:
    """The fixture itself documents the header's required identifier type."""
    clinic = create_clinic(slug="uuid")

    assert isinstance(clinic.pk, UUID)
