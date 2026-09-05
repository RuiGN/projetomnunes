"""Tests for Sprint 20 Secure API and Integrations Portal (8.20.1)."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ValidationError

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from integrations import services
from integrations.contracts import (
    FORBIDDEN_API_SCOPES,
    ApiAuthenticationError,
    ApiAuthorizationError,
    IdempotencyConflictError,
    RateLimitExceededError,
    ScopeInsufficientError,
)
from integrations.models import (
    ApiClientSecret,
    ApiClientStatus,
    ApiClientType,
    IntegrationAuditMetric,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic_alpha() -> Clinic:
    return ClinicFactory.create(name="Clínica Alpha")


@pytest.fixture
def clinic_beta() -> Clinic:
    return ClinicFactory.create(name="Clínica Beta")


@pytest.fixture
def admin_user(clinic_alpha: Clinic) -> User:
    user = UserFactory.create(email="admin.alpha@test.org")
    ClinicMembershipFactory.create(
        clinic=clinic_alpha,
        user=user,
        role=ClinicMembership.Role.CLINIC_ADMIN,
        is_active=True,
    )
    return user


@pytest.mark.django_db
def test_api_openapi_spec_and_forbidden_scope_enforcement(
    clinic_alpha: Clinic, admin_user: User
) -> None:
    """OpenAPI spec documents scopes and deprecation; forbidden scopes are rejected."""
    spec = services.get_api_openapi_spec()
    assert spec["openapi"] == "3.1.0"
    assert "Sunset" in spec["deprecation_policy"]["sunset_header"]
    assert (
        "patients:read"
        in spec["components"]["securitySchemes"]["OAuth2"]["flows"][
            "clientCredentials"
        ]["scopes"]
    )

    # Reject forbidden scopes
    for forbidden in FORBIDDEN_API_SCOPES:
        with pytest.raises(ValidationError, match="strictly forbidden"):
            services.register_api_client(
                clinic_id=clinic_alpha.id,
                actor_id=admin_user.id,
                client_name="Malicious Partner App",
                allowed_scopes=[forbidden],
            )


@pytest.mark.django_db
def test_api_client_registration_and_secret_rotation(
    clinic_alpha: Clinic, admin_user: User
) -> None:
    """Confidential clients have hashed secrets and support grace periods."""
    client, raw_secret = services.register_api_client(
        clinic_id=clinic_alpha.id,
        actor_id=admin_user.id,
        client_name="Parceiro Laboratório Diagnósticos",
        client_type=ApiClientType.CONFIDENTIAL,
        allowed_scopes=["patients:read", "appointments:read"],
        contact_email="dev@lab.com",
    )

    assert client.status == ApiClientStatus.ACTIVE
    assert client.client_id.startswith("cli_")
    assert raw_secret not in [client.client_id, client.client_name]

    # Secret is stored hashed
    secret_rec = (
        ApiClientSecret.objects.for_clinic(clinic_alpha.id)
        .filter(client=client)
        .first()
    )
    assert secret_rec is not None
    assert secret_rec.secret_hash != raw_secret
    assert secret_rec.secret_hint == raw_secret[-4:]

    # Secret rotation
    new_sec, new_raw = services.rotate_client_secret(
        clinic_id=clinic_alpha.id,
        client_id=client.client_id,
        actor_id=admin_user.id,
        grace_period_days=7,
    )
    assert new_raw != raw_secret
    assert new_sec.secret_hint == new_raw[-4:]

    # Old secret is given an expiration timestamp
    old_sec = (
        ApiClientSecret.objects.for_clinic(clinic_alpha.id)
        .filter(id=secret_rec.id)
        .first()
    )
    assert old_sec is not None
    assert old_sec.rotated_at is not None
    assert old_sec.expires_at is not None


@pytest.mark.django_db
def test_api_token_lifecycle_authentication_and_scopes(
    clinic_alpha: Clinic, admin_user: User
) -> None:
    """Tokens are short-lived, validated per scope, and can be immediately revoked."""
    client, raw_secret = services.register_api_client(
        clinic_id=clinic_alpha.id,
        actor_id=admin_user.id,
        client_name="App Parceiro Agendamentos",
        allowed_scopes=["appointments:read", "appointments:write"],
    )

    # Issue token with invalid secret -> fail
    with pytest.raises(
        ApiAuthenticationError, match="Invalid or expired client secret"
    ):
        services.issue_api_token(
            clinic_id=clinic_alpha.id,
            client_id=client.client_id,
            client_secret="wrong-secret-token",
        )

    # Issue token with scope not allowed -> fail
    with pytest.raises(ScopeInsufficientError, match="not permitted to request scope"):
        services.issue_api_token(
            clinic_id=clinic_alpha.id,
            client_id=client.client_id,
            client_secret=raw_secret,
            requested_scopes=["patients:write"],
        )

    # Issue token successfully
    token_obj, raw_token = services.issue_api_token(
        clinic_id=clinic_alpha.id,
        client_id=client.client_id,
        client_secret=raw_secret,
        requested_scopes=["appointments:read"],
        ttl_seconds=3600,
    )
    assert raw_token.startswith("omni_tok_")
    assert token_obj.scopes == ["appointments:read"]

    # Validate token
    validated_client, validated_token = services.validate_api_token(
        raw_token=raw_token,
        required_scope="appointments:read",
        expected_clinic_id=clinic_alpha.id,
    )
    assert validated_client.id == client.id
    assert validated_token.id == token_obj.id

    # Validate with missing scope -> fail
    with pytest.raises(ScopeInsufficientError, match="lacks required scope"):
        services.validate_api_token(
            raw_token=raw_token,
            required_scope="appointments:write",
        )

    # Revoke token
    assert services.revoke_api_token(raw_token_or_jti=token_obj.jti) is True
    with pytest.raises(ApiAuthenticationError, match="Invalid or revoked"):
        services.validate_api_token(raw_token=raw_token)


@pytest.mark.django_db
def test_multi_tenant_isolation_rejects_cross_tenant_token(
    clinic_alpha: Clinic, clinic_beta: Clinic, admin_user: User
) -> None:
    """A valid token issued for Clinic Alpha cannot access Clinic Beta."""
    client, raw_secret = services.register_api_client(
        clinic_id=clinic_alpha.id,
        actor_id=admin_user.id,
        client_name="Alpha Exclusivo",
        allowed_scopes=["patients:read"],
    )
    _, raw_token = services.issue_api_token(
        clinic_id=clinic_alpha.id,
        client_id=client.client_id,
        client_secret=raw_secret,
    )

    with pytest.raises(ApiAuthorizationError, match="Tenant mismatch"):
        services.validate_api_token(
            raw_token=raw_token,
            expected_clinic_id=clinic_beta.id,
        )


@pytest.mark.django_db
def test_api_client_revocation_invalidates_all_tokens(
    clinic_alpha: Clinic, admin_user: User
) -> None:
    """Revoking an API client immediately invalidates all active tokens and secrets."""
    client, raw_secret = services.register_api_client(
        clinic_id=clinic_alpha.id,
        actor_id=admin_user.id,
        client_name="Parceiro a ser revogado",
        allowed_scopes=["patients:read"],
    )
    _, raw_token = services.issue_api_token(
        clinic_id=clinic_alpha.id,
        client_id=client.client_id,
        client_secret=raw_secret,
    )

    # Valid before revocation
    services.validate_api_token(raw_token=raw_token)

    # Revoke client
    services.revoke_api_client(
        clinic_id=clinic_alpha.id,
        client_id=client.client_id,
        actor_id=admin_user.id,
        reason="Compromisso de segurança encerrado",
    )

    with pytest.raises(ApiAuthenticationError, match="Invalid or revoked access token"):
        services.validate_api_token(raw_token=raw_token)


@pytest.mark.django_db
def test_api_idempotency_caching_and_conflict_detection(
    clinic_alpha: Clinic, admin_user: User
) -> None:
    """Identical idempotency key returns cache; different payload raises conflict."""
    client, _ = services.register_api_client(
        clinic_id=clinic_alpha.id,
        actor_id=admin_user.id,
        client_name="Idempotency Tester",
    )

    call_count = 0

    def sample_mutation() -> tuple[int, dict[str, Any]]:
        nonlocal call_count
        call_count += 1
        return 201, {"resource_id": "item_123", "call": call_count}

    # First call: executes mutation
    status1, body1 = services.process_api_idempotency(
        clinic_id=clinic_alpha.id,
        client_id=client.client_id,
        idempotency_key="idemp_key_001",
        request_payload={"full_name": "Paciente Teste"},
        handler_fn=sample_mutation,
    )
    assert status1 == 201
    assert body1 == {"resource_id": "item_123", "call": 1}
    assert call_count == 1

    # Second call with identical payload: returns cached response
    status2, body2 = services.process_api_idempotency(
        clinic_id=clinic_alpha.id,
        client_id=client.client_id,
        idempotency_key="idemp_key_001",
        request_payload={"full_name": "Paciente Teste"},
        handler_fn=sample_mutation,
    )
    assert status2 == 201
    assert body2 == {"resource_id": "item_123", "call": 1}
    assert call_count == 1  # Not incremented!

    # Third call with conflicting payload for same key: raises IdempotencyConflictError
    with pytest.raises(IdempotencyConflictError, match="mismatched request payload"):
        services.process_api_idempotency(
            clinic_id=clinic_alpha.id,
            client_id=client.client_id,
            idempotency_key="idemp_key_001",
            request_payload={"full_name": "Paciente Alterado Fraudulento"},
            handler_fn=sample_mutation,
        )


@pytest.mark.django_db
def test_api_rate_limiting_enforcement(clinic_alpha: Clinic, admin_user: User) -> None:
    """Rate limit per tenant/client rejects bursts beyond quota."""
    client, _ = services.register_api_client(
        clinic_id=clinic_alpha.id,
        actor_id=admin_user.id,
        client_name="Quota Tester",
    )

    # Simulate 3 requests
    for _ in range(3):
        IntegrationAuditMetric.infrastructure_objects.create(
            clinic_id=clinic_alpha.id,
            provider=client.client_id,
            operation="api_call",
            outcome="success",
        )

    # Limit of 5 -> allowed with remaining 1
    allowed, remaining = services.check_rate_limit(
        clinic_id=clinic_alpha.id,
        client_id=client.client_id,
        limit_rpm=5,
    )
    assert allowed is True
    assert remaining == 1

    # Limit of 3 -> raises RateLimitExceededError
    with pytest.raises(RateLimitExceededError, match="Rate limit exceeded"):
        services.check_rate_limit(
            clinic_id=clinic_alpha.id,
            client_id=client.client_id,
            limit_rpm=3,
        )
