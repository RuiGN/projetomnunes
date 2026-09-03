"""Acceptance tests for the versioned CFP/CRP-02 regulatory release gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = PROJECT_ROOT / "docs" / "compliance" / "cfp-crp02-matrix.json"
CHECK_SCRIPT = PROJECT_ROOT / "scripts" / "check_regulatory_matrix.py"
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "quality.yml"


def load_matrix() -> dict[str, Any]:
    """Load the repository's authoritative regulatory matrix."""
    return cast(dict[str, Any], json.loads(MATRIX_PATH.read_text(encoding="utf-8")))


def run_check(path: Path) -> subprocess.CompletedProcess[str]:
    """Execute the same standalone release gate used by CI."""
    return subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), "--matrix", str(path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


def write_variant(tmp_path: Path, matrix: dict[str, Any]) -> Path:
    """Persist one synthetic matrix variant for fail-closed checks."""
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(matrix), encoding="utf-8")
    return path


def accepted_matrix() -> dict[str, Any]:
    """Build a structurally valid accepted variant for integrity mutations."""
    matrix = deepcopy(load_matrix())
    evidence_digest = hashlib.sha256(MATRIX_PATH.read_bytes()).hexdigest()
    release_scope = matrix["release_decision"]["scope"]
    for acceptance in matrix["acceptances"]:
        acceptance.update(
            {
                "status": "accepted",
                "approver": "Named reviewer",
                "accepted_at": "2026-09-01T08:00:00-03:00",
                "scope": release_scope,
                "decision": "Accepted",
                "review_due_at": "2026-09-30",
                "matrix_version": matrix["version"],
                "evidence_path": "docs/compliance/cfp-crp02-matrix.json",
                "evidence_sha256": evidence_digest,
            }
        )
    matrix["release_decision"]["status"] = "approved"
    return matrix


def test_matrix_covers_initial_cfp_and_crp02_scope_with_traceable_obligations() -> None:
    """The baseline links authoritative acts to product controls and evidence."""
    matrix = load_matrix()
    act_ids = {act["id"] for act in matrix["acts"]}

    assert {
        "CFP-RES-010-2005",
        "CFP-RES-001-2009",
        "CFP-RES-006-2019",
        "CFP-RES-016-2019",
        "CFP-RES-008-2023",
        "CFP-RES-009-2024",
        "CRP02-PJ-GUIDANCE",
    } <= act_ids
    assert matrix["jurisdiction"] == "Brazil / CRP-02 Pernambuco"
    assert matrix["release_decision"]["status"] == "blocked"
    assert matrix["obligations"]
    legal_entity_act = next(
        act for act in matrix["acts"] if act["id"] == "CFP-RES-016-2019"
    )
    assert legal_entity_act["effective_from"] == "2019-11-04"
    assert "CFP Resolution 08/2023" in legal_entity_act["history"]

    required = {
        "id",
        "act_id",
        "provision",
        "effective_status",
        "history",
        "scope",
        "jurisdiction",
        "product_applicability",
        "derived_requirement",
        "evidence",
        "verification",
        "noncompliance_risk",
        "backlog_tasks",
        "acceptance_owners",
        "last_reviewed_at",
    }
    for obligation in matrix["obligations"]:
        assert required <= obligation.keys()
        assert obligation["evidence"]
        assert obligation["verification"]
        assert obligation["backlog_tasks"]


def test_repository_matrix_passes_completeness_gate_while_release_stays_blocked() -> (
    None
):
    """Pending human acceptance is explicit and cannot look like approval."""
    completed = run_check(MATRIX_PATH)

    assert completed.returncode == 0, completed.stderr
    assert "matrix complete; regulated release blocked" in completed.stdout


def test_gate_rejects_missing_traceability_field(tmp_path: Path) -> None:
    """An obligation without evidence cannot satisfy the regulated gate."""
    matrix = deepcopy(load_matrix())
    del matrix["obligations"][0]["evidence"]

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "evidence" in completed.stderr


def test_gate_rejects_nonexistent_obligation_evidence_and_verification(
    tmp_path: Path,
) -> None:
    """Traceability entries must resolve to repository evidence or procedures."""
    matrix = deepcopy(load_matrix())
    matrix["obligations"][0]["evidence"] = ["does/not/exist"]
    matrix["obligations"][0]["verification"] = ["no executable check"]

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "evidence reference does not exist" in completed.stderr
    assert "verification reference does not exist" in completed.stderr


def test_gate_rejects_release_without_current_human_acceptances(tmp_path: Path) -> None:
    """A caller cannot mark regulated work releasable around pending owners."""
    matrix = deepcopy(load_matrix())
    matrix["release_decision"]["status"] = "approved"

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "clinical and legal/regulatory approvals" in completed.stderr


def test_gate_rejects_unverifiable_human_acceptances(tmp_path: Path) -> None:
    """Typed names alone cannot authorize a regulated release."""
    matrix = deepcopy(load_matrix())
    for acceptance in matrix["acceptances"]:
        acceptance.update(
            {
                "status": "accepted",
                "approver": "Named reviewer",
                "accepted_at": "2026-09-01T12:00:00Z",
                "decision": "Accepted",
                "review_due_at": "2026-09-30",
            }
        )
    matrix["release_decision"]["status"] = "approved"

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "matrix_version" in completed.stderr
    assert "evidence_path" in completed.stderr
    assert "evidence_sha256" in completed.stderr


def test_gate_rejects_missing_acceptance_evidence_file(tmp_path: Path) -> None:
    """An acceptance artifact must exist inside the repository."""
    matrix = deepcopy(load_matrix())
    for acceptance in matrix["acceptances"]:
        acceptance.update(
            {
                "status": "accepted",
                "approver": "Named reviewer",
                "accepted_at": "2026-09-01T12:00:00Z",
                "decision": "Accepted",
                "review_due_at": "2026-09-30",
                "matrix_version": matrix["version"],
                "evidence_path": "docs/compliance/approvals/missing.txt",
                "evidence_sha256": "0" * 64,
            }
        )
    matrix["release_decision"]["status"] = "approved"

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "evidence_path does not exist" in completed.stderr


def test_gate_rejects_mismatched_acceptance_evidence_digest(tmp_path: Path) -> None:
    """A changed approval artifact invalidates the recorded acceptance."""
    matrix = deepcopy(load_matrix())
    for acceptance in matrix["acceptances"]:
        acceptance.update(
            {
                "status": "accepted",
                "approver": "Named reviewer",
                "accepted_at": "2026-09-01T12:00:00Z",
                "decision": "Accepted",
                "review_due_at": "2026-09-30",
                "matrix_version": matrix["version"],
                "evidence_path": "docs/compliance/cfp-crp02-matrix.json",
                "evidence_sha256": "0" * 64,
            }
        )
    matrix["release_decision"]["status"] = "approved"

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "evidence_sha256 does not match" in completed.stderr


def test_gate_rejects_invalid_acceptance_timestamp(tmp_path: Path) -> None:
    """An accepted decision needs a parseable, attributable timestamp."""
    matrix = deepcopy(load_matrix())
    evidence_digest = hashlib.sha256(MATRIX_PATH.read_bytes()).hexdigest()
    for acceptance in matrix["acceptances"]:
        acceptance.update(
            {
                "status": "accepted",
                "approver": "Named reviewer",
                "accepted_at": "not-a-timestamp",
                "decision": "Accepted",
                "review_due_at": "2026-09-30",
                "matrix_version": matrix["version"],
                "evidence_path": "docs/compliance/cfp-crp02-matrix.json",
                "evidence_sha256": evidence_digest,
            }
        )
    matrix["release_decision"]["status"] = "approved"

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "accepted_at must be an ISO timestamp" in completed.stderr


def test_gate_rejects_unassessed_or_stale_normative_source(tmp_path: Path) -> None:
    """Every source needs a recent explicit review and effective status."""
    matrix = deepcopy(load_matrix())
    matrix["acts"][0]["last_verified_at"] = "2025-01-01"

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "stale" in completed.stderr


def test_gate_rejects_invalid_obligation_effective_from(tmp_path: Path) -> None:
    """An obligation needs a parseable date from which it applies."""
    matrix = deepcopy(load_matrix())
    matrix["obligations"][0]["effective_from"] = "not-a-date"

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "effective_from must be an ISO date" in completed.stderr


def test_gate_rejects_unassessed_obligation_effective_status(tmp_path: Path) -> None:
    """An obligation cannot pass without an assessed effective status."""
    matrix = deepcopy(load_matrix())
    matrix["obligations"][0]["effective_status"] = "unknown"

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "effective_status must be assessed as effective" in completed.stderr


def test_gate_rejects_backlog_task_missing_from_prd(tmp_path: Path) -> None:
    """Traceability must point to an actual checklist identifier in the PRD."""
    matrix = deepcopy(load_matrix())
    matrix["obligations"][0]["backlog_tasks"] = ["8.99.99"]

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "backlog_tasks references unknown PRD id: 8.99.99" in completed.stderr


def test_gate_rejects_future_acceptance_timestamp(tmp_path: Path) -> None:
    """A human decision cannot be recorded before it actually occurs."""
    matrix = accepted_matrix()
    matrix["acceptances"][0]["accepted_at"] = "2999-01-01T00:00:00Z"

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "accepted_at cannot be in the future" in completed.stderr


def test_gate_rejects_nonaffirmative_accepted_decision(tmp_path: Path) -> None:
    """Accepted status requires an explicit affirmative decision."""
    matrix = accepted_matrix()
    matrix["acceptances"][0]["decision"] = "Pending legal conditions"

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "decision must be affirmative" in completed.stderr


def test_gate_rejects_acceptance_for_different_release_scope(tmp_path: Path) -> None:
    """Approval evidence must authorize the exact release scope."""
    matrix = accepted_matrix()
    matrix["acceptances"][0]["scope"] = "A narrower unrelated scope"

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "scope must match release_decision.scope" in completed.stderr


@pytest.mark.parametrize("next_review_at", ["not-a-date", "2026-08-31"])
def test_gate_rejects_invalid_or_expired_release_review(
    tmp_path: Path, next_review_at: str
) -> None:
    """The release decision must always carry a current review deadline."""
    matrix = deepcopy(load_matrix())
    matrix["release_decision"]["next_review_at"] = next_review_at

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "release_decision.next_review_at" in completed.stderr


def test_gate_rejects_unsupported_matrix_schema(tmp_path: Path) -> None:
    """Unknown matrix shapes fail closed instead of being partially interpreted."""
    matrix = deepcopy(load_matrix())
    matrix["schema_version"] = 99

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "matrix.schema_version must equal 1" in completed.stderr


def test_gate_rejects_stale_matrix_review_metadata(tmp_path: Path) -> None:
    """The matrix-level review date is mandatory and freshness-bound."""
    matrix = deepcopy(load_matrix())
    matrix["last_reviewed_at"] = "2025-01-01"

    completed = run_check(write_variant(tmp_path, matrix))

    assert completed.returncode != 0
    assert "matrix.last_reviewed_at is stale or in the future" in completed.stderr


def test_ci_executes_regulatory_matrix_gate() -> None:
    """The release check cannot be skipped by the normal quality pipeline."""
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "python scripts/check_regulatory_matrix.py" in workflow
