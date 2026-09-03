"""Safe request correlation, structured logging, health, and error-page tests."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_request_id_accepts_safe_value_and_returns_response_header(
    client: Client,
) -> None:
    response = client.get("/", headers={"X-Request-ID": "safe-request_123.abc"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "safe-request_123.abc"


@pytest.mark.parametrize(
    "value",
    ("", " spaces ", "contains/slash", "a" * 65, "quebra\nlinha", "ç"),
)
def test_request_id_replaces_missing_or_unsafe_values(
    client: Client, value: str
) -> None:
    headers = {"X-Request-ID": value} if value else {}

    response = client.get("/", headers=headers)
    generated = response.headers["X-Request-ID"]

    assert generated
    assert generated != value
    assert len(generated) <= 64
    assert generated.isascii()


def test_request_context_is_isolated_between_concurrent_calls() -> None:
    from core.middleware import RequestCorrelationMiddleware
    from core.observability import current_request_id

    barrier_values: list[str] = []

    def endpoint(request: HttpRequest) -> HttpResponse:
        barrier_values.append(current_request_id())
        return HttpResponse(current_request_id())

    middleware = RequestCorrelationMiddleware(endpoint)
    factory = RequestFactory()

    def invoke(request_id: str) -> str:
        response = middleware(factory.get("/", headers={"X-Request-ID": request_id}))
        return response.content.decode()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(invoke, ("request-one", "request-two")))

    assert sorted(results) == ["request-one", "request-two"]
    assert sorted(barrier_values) == ["request-one", "request-two"]
    assert current_request_id() == "unknown"


def test_json_logging_contains_only_safe_structured_context() -> None:
    from core.observability import JsonLogFormatter, bind_request_context

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger = logging.getLogger("tests.safe-json")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    reset = bind_request_context(
        request_id="req-123",
        tenant_id="tenant-456",
        actor_id="actor-sensitive-id",
    )
    try:
        logger.info(
            "clinical body must not appear",
            extra={
                "event": "request.completed",
                "outcome": "success",
                "latency_ms": 12.5,
                "password": "secret-password",
                "token": "raw-token",
                "request_body": {"mood": "private"},
                "non_serializable": object(),
            },
        )
    finally:
        reset()

    payload = json.loads(stream.getvalue())
    serialized = json.dumps(payload)
    assert payload["request_id"] == "req-123"
    assert payload["tenant_id"] == "tenant-456"
    assert payload["actor_ref"].startswith("actor_")
    assert payload["actor_ref"] != "actor-sensitive-id"
    assert payload["event"] == "request.completed"
    assert payload["outcome"] == "success"
    assert payload["latency_ms"] == 12.5
    assert "clinical body" not in serialized
    assert "secret-password" not in serialized
    assert "raw-token" not in serialized
    assert "private" not in serialized


def test_django_logging_uses_one_structured_handler_without_propagation() -> None:
    """Django records cannot bypass JSON formatting or be emitted twice."""
    from core.observability import JsonLogFormatter

    django_logger = logging.getLogger("django")

    assert len(django_logger.handlers) == 1
    assert isinstance(django_logger.handlers[0].formatter, JsonLogFormatter)
    assert django_logger.propagate is False


def test_tenant_denial_keeps_request_correlation(client: Client) -> None:
    user = User.objects.create_user(email="correlated-user@example.test")
    client.force_login(user)

    response = client.get("/", headers={"X-Request-ID": "tenant-denied-123"})

    assert response.status_code == 400
    assert response.headers["X-Request-ID"] == "tenant-denied-123"


def test_liveness_does_not_touch_database_or_cache(client: Client) -> None:
    with (
        patch("django.db.connection.ensure_connection") as ensure_connection,
        patch.object(cache, "set") as cache_set,
    ):
        response = client.get("/health/live/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    ensure_connection.assert_not_called()
    cache_set.assert_not_called()


def test_readiness_checks_database_and_cache(client: Client) -> None:
    response = client.get("/health/ready/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_hides_database_failure_details(client: Client) -> None:
    with patch(
        "config.views.connection.ensure_connection",
        side_effect=DatabaseError("password=leaked internal-host"),
    ):
        response = client.get("/health/ready/")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert b"leaked" not in response.content
    assert b"internal-host" not in response.content


def test_readiness_hides_cache_failure_details(client: Client) -> None:
    with patch.object(cache, "set", side_effect=RuntimeError("redis-secret")):
        response = client.get("/health/ready/")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert b"redis-secret" not in response.content


def test_health_is_narrow_tenant_exemption_for_authenticated_probe(
    client: Client,
) -> None:
    user = User.objects.create_user(email="health-probe@example.test")
    client.force_login(user)

    health = client.get("/health/live/")
    ordinary = client.get("/")

    assert health.status_code == 200
    assert ordinary.status_code == 400


@pytest.mark.parametrize(
    ("handler_name", "status_code", "expected_text"),
    (
        ("bad_request", 400, "Não foi possível processar sua solicitação."),
        (
            "permission_denied",
            403,
            "Você não tem permissão para acessar este conteúdo.",
        ),
        ("page_not_found", 404, "A página solicitada não foi encontrada."),
        ("server_error", 500, "Ocorreu um erro inesperado."),
    ),
)
def test_safe_error_pages_are_pt_br_and_include_correlation_reference(
    handler_name: str,
    status_code: int,
    expected_text: str,
) -> None:
    from config import views

    request = RequestFactory().get("/missing/")
    request.user = AnonymousUser()
    request.request_id = "error-reference-123"  # type: ignore[attr-defined]
    handler = getattr(views, handler_name)
    response = handler(request, Exception("secret stack content"))
    response.render()

    assert response.status_code == status_code
    assert expected_text in response.content.decode()
    assert "error-reference-123" in response.content.decode()
    assert "secret stack content" not in response.content.decode()


def test_health_path_exemption_is_exact_prefix() -> None:
    from clinics.middleware import is_tenant_exempt_path

    assert is_tenant_exempt_path("/health/live/") is True
    assert is_tenant_exempt_path("/health/ready/") is True
    assert is_tenant_exempt_path("/healthcare/") is False
