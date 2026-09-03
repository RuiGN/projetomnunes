"""Smoke tests for the Django project foundation."""

import os
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest
from django.core.checks import run_checks
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test import Client
from django.urls import resolve


def test_test_settings_import() -> None:
    """The isolated test settings module can be imported."""
    settings_module = import_module("config.settings.test")

    assert settings_module.LANGUAGE_CODE == "pt-br"


def test_root_url_resolves_to_home() -> None:
    """The project root resolves to the named foundation endpoint."""
    match = resolve("/")

    assert match.url_name == "home"


def test_root_endpoint_uses_brazilian_portuguese(client: Client) -> None:
    """The only user-visible foundation response is in PT-BR."""
    response = client.get("/")

    assert response.status_code == 200
    assert response.content.decode() == "Plataforma terapêutica disponível."


@pytest.mark.django_db
def test_database_connection() -> None:
    """The hermetic test database accepts a basic query."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        row = cursor.fetchone()

    assert row == (1,)


@pytest.mark.django_db
def test_django_system_checks() -> None:
    """Django's system check framework reports no issues, including DB features."""
    assert run_checks() == []


def test_production_settings_reject_missing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production fails clearly when mandatory configuration is absent."""
    for name in (
        "DJANGO_SECRET_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "DB_HOST",
        "DB_PORT",
    ):
        monkeypatch.delenv(name, raising=False)
    sys.modules.pop("config.settings.production", None)

    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        import_module("config.settings.production")


def test_environment_settings_avoid_wildcard_imports() -> None:
    """Environment composition remains explicit and reviewable."""
    settings_dir = Path(__file__).parents[1] / "config" / "settings"

    for filename in ("development.py", "production.py", "test.py"):
        source = (settings_dir / filename).read_text()
        assert "import *" not in source


def test_test_settings_can_select_postgresql_for_ci() -> None:
    """CI can exercise the same PostgreSQL engine required in production."""
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings.test",
            "TEST_DATABASE": "postgresql",
            "DB_NAME": "test_name",
            "DB_USER": "test_user",
            "DB_PASSWORD": "test_password",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "5432",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from django.conf import settings; "
                "print(settings.DATABASES['default']['ENGINE'])"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.stdout.strip() == "django.db.backends.postgresql"
