"""Tests for explicit domain boundaries and their public contracts."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from django.apps import apps

from tests.architecture_helpers import architecture_violations, domain_dependencies

DOMAIN_MODULES = (
    "core",
    "tenancy",
    "accounts",
    "clinics",
    "people",
    "consents",
    "audit",
    "content",
    "privacy",
    "therapist_dashboard",
    "onboarding",
    "journal",
    "goals",
    "scheduling",
    "analytics",
    "finance",
)

ALLOWED_DEPENDENCIES = {
    "core": set(),
    "tenancy": {"core"},
    "accounts": {"clinics", "core", "tenancy"},
    "clinics": {"core", "tenancy"},
    "people": {"accounts", "clinics", "core", "tenancy"},
    "consents": {"accounts", "audit", "clinics", "core", "people", "tenancy"},
    "audit": {"accounts", "clinics", "core", "journal", "people"},
    "privacy": {"accounts", "audit", "clinics", "content", "core"},
    "content": {"accounts", "audit", "clinics", "core", "people", "tenancy"},
    "therapist_dashboard": {
        "accounts",
        "audit",
        "clinics",
        "consents",
        "core",
        "people",
        "tenancy",
    },
    "onboarding": {
        "accounts",
        "clinics",
        "consents",
        "core",
        "people",
        "tenancy",
    },
    "journal": {
        "accounts",
        "clinics",
        "core",
        "people",
        "tenancy",
    },
    "goals": {
        "accounts",
        "clinics",
        "core",
        "people",
        "tenancy",
    },
    "scheduling": {
        "audit",
        "clinics",
        "core",
        "goals",
        "people",
    },
    "analytics": {
        "audit",
        "clinics",
        "core",
        "goals",
        "journal",
        "people",
        "scheduling",
    },
    "finance": {
        "audit",
        "clinics",
        "core",
        "scheduling",
    },
}


def test_all_domain_apps_are_registered_with_explicit_configs() -> None:
    """All requested domain boundaries are active Django apps."""
    for module in DOMAIN_MODULES:
        config = apps.get_app_config(module)
        assert config.name == module
        assert config.__class__.__module__ == f"{module}.apps"


@pytest.mark.parametrize("module", DOMAIN_MODULES)
def test_each_domain_exposes_minimal_interfaces(module: str) -> None:
    """Every domain exposes the shared explicit contract categories."""
    service = import_module(f"{module}.services")
    selector = import_module(f"{module}.selectors")
    policy = import_module(f"{module}.policies")
    events = import_module(f"{module}.events")

    assert hasattr(service.Service, "execute")
    assert hasattr(selector.Selector, "select")
    assert hasattr(policy.AuthorizationPolicy, "is_allowed")
    assert issubclass(events.DomainEvent, object)


def test_required_domain_events_are_typed_and_immutable() -> None:
    """Required event contracts carry typed IDs and cannot be changed."""
    from accounts.events import InvitationCreated
    from clinics.events import ClinicCreated
    from consents.events import ConsentGranted, ConsentRevoked
    from people.events import ProfessionalPatientRelationshipCreated

    event_id = uuid4()
    occurred_at = datetime.now(UTC)
    actor_id = uuid4()
    tenant_id = uuid4()
    clinic_id = uuid4()
    professional_id = uuid4()
    patient_id = uuid4()
    relationship_id = uuid4()
    consent_id = uuid4()

    events = (
        ClinicCreated(event_id, occurred_at, actor_id, tenant_id, clinic_id),
        InvitationCreated(event_id, occurred_at, actor_id, tenant_id, uuid4()),
        ProfessionalPatientRelationshipCreated(
            event_id,
            occurred_at,
            actor_id,
            tenant_id,
            relationship_id,
            professional_id,
            patient_id,
        ),
        ConsentGranted(
            event_id,
            occurred_at,
            actor_id,
            tenant_id,
            consent_id,
            professional_id,
            patient_id,
        ),
        ConsentRevoked(
            event_id,
            occurred_at,
            actor_id,
            tenant_id,
            consent_id,
            professional_id,
            patient_id,
        ),
    )

    assert all(isinstance(event.event_id, UUID) for event in events)
    assert all(event.occurred_at.tzinfo is not None for event in events)
    with pytest.raises(FrozenInstanceError):
        events[0].clinic_id = uuid4()  # type: ignore[misc]


def test_domain_source_respects_allowed_dependencies() -> None:
    """The checked-in source has no forbidden imports or dependency cycles."""
    project_root = Path(__file__).parents[1]
    dependencies = domain_dependencies(project_root, DOMAIN_MODULES)

    assert architecture_violations(dependencies, ALLOWED_DEPENDENCIES) == []


def test_core_persistence_is_a_target_specific_public_boundary(tmp_path: Path) -> None:
    """Domains may import only the named persistence base from its public module."""
    for module in ("core", "clinics"):
        (tmp_path / module).mkdir()
        (tmp_path / module / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "clinics" / "consumer.py").write_text(
        "from core.persistence import UUIDTimestampedModel\n",
        encoding="utf-8",
    )

    dependencies = domain_dependencies(tmp_path, ("core", "clinics"))

    assert (
        architecture_violations(
            dependencies,
            {"core": set(), "clinics": {"core"}},
        )
        == []
    )


@pytest.mark.parametrize(
    "source, expected",
    (
        (
            "from core.models import UUIDTimestampedModel\n",
            "clinics imports private module core.models",
        ),
        (
            "from core.persistence import InternalModel\n",
            "clinics imports private module core.persistence.InternalModel",
        ),
    ),
)
def test_core_persistence_allowance_does_not_expose_private_models(
    tmp_path: Path,
    source: str,
    expected: str,
) -> None:
    """The shared base allowance does not publish model modules or other symbols."""
    for module in ("core", "clinics"):
        (tmp_path / module).mkdir()
        (tmp_path / module / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "clinics" / "consumer.py").write_text(source, encoding="utf-8")

    dependencies = domain_dependencies(tmp_path, ("core", "clinics"))

    assert architecture_violations(
        dependencies,
        {"core": set(), "clinics": {"core"}},
    ) == [expected]


def test_architecture_check_detects_forbidden_imports_and_cycles(
    tmp_path: Path,
) -> None:
    """The architecture guard demonstrably fails on both violation classes."""
    for module in ("core", "accounts"):
        (tmp_path / module).mkdir()
        (tmp_path / module / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "core" / "bad.py").write_text("import accounts\n", encoding="utf-8")
    (tmp_path / "accounts" / "bad.py").write_text("import core\n", encoding="utf-8")

    dependencies = domain_dependencies(tmp_path, ("core", "accounts"))
    violations = architecture_violations(
        dependencies,
        {"core": set(), "accounts": {"core"}},
    )

    assert "core imports forbidden module accounts" in violations
    assert any(violation.startswith("dependency cycle:") for violation in violations)


def test_architecture_check_rejects_private_import_on_allowed_edge(
    tmp_path: Path,
) -> None:
    """Allowed domain edges expose public boundaries, not implementation modules."""
    for module in ("accounts", "people"):
        (tmp_path / module).mkdir()
        (tmp_path / module / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "people" / "bad.py").write_text(
        "from accounts.models import User\nfrom accounts.services import Service\n",
        encoding="utf-8",
    )

    dependencies = domain_dependencies(tmp_path, ("accounts", "people"))
    violations = architecture_violations(
        dependencies,
        {"accounts": set(), "people": {"accounts"}},
    )

    assert violations == ["people imports private module accounts.models"]


def test_accounts_uses_only_public_clinic_and_audit_boundaries(tmp_path: Path) -> None:
    """Identity workflows may orchestrate tenants and audit without model imports."""
    for module in ("accounts", "audit", "clinics"):
        (tmp_path / module).mkdir()
        (tmp_path / module / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "accounts" / "consumer.py").write_text(
        "from audit.services import record_audit_event\n"
        "from clinics.selectors import active_clinics_for_actor\n"
        "from clinics.services import create_clinic_membership\n"
        "from audit.models import AuditEvent\n"
        "from clinics.models import Clinic\n",
        encoding="utf-8",
    )

    dependencies = domain_dependencies(tmp_path, ("accounts", "audit", "clinics"))

    assert architecture_violations(
        dependencies,
        {"accounts": {"audit", "clinics"}, "audit": set(), "clinics": set()},
    ) == [
        "accounts imports private module audit.models",
        "accounts imports private module clinics.models",
    ]


def test_clinics_no_longer_depends_on_accounts(tmp_path: Path) -> None:
    """Tenant authorization uses the framework-neutral core actor policy."""
    for module in ("accounts", "clinics"):
        (tmp_path / module).mkdir()
        (tmp_path / module / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "clinics" / "consumer.py").write_text(
        "from accounts.policies import current_actor_is_active\n",
        encoding="utf-8",
    )

    dependencies = domain_dependencies(tmp_path, ("accounts", "clinics"))

    assert architecture_violations(
        dependencies,
        {"accounts": set(), "clinics": set()},
    ) == ["clinics imports forbidden module accounts"]


def test_architecture_check_rejects_literal_import_module_bypass(
    tmp_path: Path,
) -> None:
    """Literal import_module calls cannot bypass a forbidden domain edge."""
    for module in ("accounts", "clinics"):
        (tmp_path / module).mkdir()
        (tmp_path / module / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "clinics" / "consumer.py").write_text(
        "from importlib import import_module\n"
        "account_models = import_module('accounts.models')\n",
        encoding="utf-8",
    )
    dependencies = domain_dependencies(tmp_path, ("accounts", "clinics"))
    assert architecture_violations(
        dependencies, {"accounts": set(), "clinics": set()}
    ) == ["clinics imports forbidden module accounts"]


def test_architecture_check_rejects_literal_dunder_import_bypass(
    tmp_path: Path,
) -> None:
    """Literal __import__ calls cannot bypass a forbidden domain edge."""
    for module in ("accounts", "clinics"):
        (tmp_path / module).mkdir()
        (tmp_path / module / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "clinics" / "consumer.py").write_text(
        "account_models = __import__('accounts.models', fromlist=('User',))\n",
        encoding="utf-8",
    )
    dependencies = domain_dependencies(tmp_path, ("accounts", "clinics"))
    assert architecture_violations(
        dependencies, {"accounts": set(), "clinics": set()}
    ) == ["clinics imports forbidden module accounts"]


@pytest.mark.parametrize(
    "source",
    (
        "import importlib\nim = importlib.import_module\nim('accounts.models')\n",
        "imp = __import__\nimp('accounts.models', fromlist=('User',))\n",
    ),
)
def test_architecture_check_rejects_direct_aliases_of_dynamic_import_helpers(
    tmp_path: Path,
    source: str,
) -> None:
    """A direct local alias cannot hide a literal dynamic domain import."""
    for module in ("accounts", "clinics"):
        (tmp_path / module).mkdir()
        (tmp_path / module / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "clinics" / "consumer.py").write_text(source, encoding="utf-8")
    dependencies = domain_dependencies(tmp_path, ("accounts", "clinics"))
    assert architecture_violations(
        dependencies, {"accounts": set(), "clinics": set()}
    ) == ["clinics imports forbidden module accounts"]


@pytest.mark.parametrize(
    "source",
    (
        "from importlib import import_module\nloader = import_module\n"
        "loader(name='accounts.policies')\n",
        "import importlib as imports\n"
        "imports.import_module(name='accounts.policies')\n",
        "loader = __import__\n"
        "loader(name='accounts.policies', fromlist=('current_actor_is_active',))\n",
    ),
)
def test_architecture_check_rejects_literal_name_keyword_bypass(
    tmp_path: Path,
    source: str,
) -> None:
    """Dynamic import helpers cannot hide literal modules in name keywords."""
    for module in ("accounts", "clinics"):
        (tmp_path / module).mkdir()
        (tmp_path / module / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "clinics" / "consumer.py").write_text(source, encoding="utf-8")
    dependencies = domain_dependencies(tmp_path, ("accounts", "clinics"))
    assert architecture_violations(
        dependencies, {"accounts": set(), "clinics": set()}
    ) == ["clinics imports forbidden module accounts"]


@pytest.mark.parametrize(
    "source",
    (
        "import importlib\nimportlib.import_module('.policies', 'accounts')\n",
        "from importlib import import_module as loader\n"
        "loader(name='.policies', package='accounts')\n",
    ),
)
def test_architecture_check_resolves_literal_relative_import_module_calls(
    tmp_path: Path,
    source: str,
) -> None:
    """Literal relative import_module targets use their literal package context."""
    for module in ("accounts", "clinics"):
        (tmp_path / module).mkdir()
        (tmp_path / module / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "clinics" / "consumer.py").write_text(source, encoding="utf-8")
    dependencies = domain_dependencies(tmp_path, ("accounts", "clinics"))
    assert architecture_violations(
        dependencies, {"accounts": set(), "clinics": set()}
    ) == ["clinics imports forbidden module accounts"]
