"""Acceptance tests for incident response, backup and continuity readiness."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = PROJECT_ROOT / "docs" / "security" / "incident-response-runbook.md"
DRILL_SCRIPT = PROJECT_ROOT / "scripts" / "incident_restore_drill.py"
POSTGRES_DRILL_SCRIPT = PROJECT_ROOT / "scripts" / "postgres_restore_drill.py"


def test_runbook_defines_severity_ownership_escalation_and_secure_channels() -> None:
    """The operational runbook assigns severity and accountable responders."""
    document = RUNBOOK.read_text(encoding="utf-8")

    for required_term in (
        "SEV-1",
        "SEV-2",
        "SEV-3",
        "SEV-4",
        "Incident Commander",
        "Data Protection Officer",
        "Legal",
        "secure incident channel",
        "escalation",
    ):
        assert required_term in document


def test_runbook_covers_containment_evidence_and_communication_decisions() -> None:
    """Containment never destroys evidence and notification remains assessed."""
    document = RUNBOOK.read_text(encoding="utf-8")

    for required_term in (
        "Account containment",
        "Session containment",
        "Integration containment",
        "Key containment",
        "Tenant containment",
        "chain of custody",
        "ANPD",
        "affected clinics",
        "affected data subjects",
        "notification decision record",
    ):
        assert required_term in document


def test_restore_drill_uses_synthetic_data_and_records_verified_results(
    tmp_path: Path,
) -> None:
    """The executable drill restores an encrypted backup and records evidence."""
    report_path = tmp_path / "incident-drill.json"

    completed = subprocess.run(
        [sys.executable, str(DRILL_SCRIPT), "--report", str(report_path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    report: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["data_classification"] == "synthetic-only"
    assert report["backup"]["encrypted"] is True
    assert report["backup"]["persisted_before_restore"] is True
    assert report["backup"]["provenance_verified"] is True
    assert report["backup"]["ciphertext_integrity_verified"] is True
    assert report["restore"]["isolated"] is True
    assert report["restore"]["source_record_count"] == 3
    assert report["restore"]["restored_record_count"] == 3
    assert report["restore"]["integrity_verified"] is True
    assert report["restore"]["corrupted_backup_rejected"] is True
    assert report["simulation"]["evidence_preserved"] is True
    assert report["simulation"]["incident_record_verified"] is True
    assert report["simulation"]["containment_verified"] is True
    assert report["simulation"]["notification_assessment_verified"] is True
    assert report["simulation"]["chain_of_custody_verified"] is True
    assert report["simulation"]["incident_id"]
    assert report["simulation"]["evidence_manifest_sha256"]
    assert report["simulation"]["failures_exercised"]
    assert report["simulation"]["corrective_actions"]
    assert report["timings_seconds"]["rto_observed"] >= 0
    assert report["timings_seconds"]["rpo_observed"] > 0
    assert (
        report["timings_seconds"]["rpo_observed"] <= report["objectives_seconds"]["rpo"]
    )
    checkpoint = datetime.fromisoformat(report["recovery_checkpoint_at"])
    controlled_change = datetime.fromisoformat(
        report["recovery"]["controlled_change_at"]
    )
    assert report["recovery"]["rpo_calculation"] == (
        "controlled_change_at - recovery_checkpoint_at"
    )
    assert report["recovery"]["source_contains_controlled_change"] is True
    assert report["recovery"]["restored_contains_controlled_change"] is False
    assert report["timings_seconds"]["rpo_observed"] == pytest.approx(
        (controlled_change - checkpoint).total_seconds(), abs=0.000001
    )
    assert checkpoint.tzinfo == UTC

    package = report["evidence_package"]
    package_path = Path(package["locator"])
    assert package_path.exists()
    package_bytes = package_path.read_bytes()
    assert hashlib.sha256(package_bytes).hexdigest() == package["sha256"]
    assert report["simulation"]["incident_id"].encode() not in package_bytes
    assert package["encrypted"] is True
    assert package["authenticated"] is True
    assert package["verified_after_temporary_cleanup"] is True
    for digest_name in (
        "artifact_sha256",
        "manifest_sha256",
        "script_sha256",
        "source_sha256",
    ):
        assert len(report["digests"][digest_name]) == 64
    assert report["digests"]["artifact_sha256"] == package["sha256"]
    assert (
        report["digests"]["script_sha256"]
        == hashlib.sha256(DRILL_SCRIPT.read_bytes()).hexdigest()
    )
    assert report["timings_seconds"]["total"] >= 0
    for action in report["simulation"]["corrective_actions"]:
        assert action["owner"]
        assert datetime.fromisoformat(action["due_at"]).tzinfo == UTC


@pytest.mark.parametrize(
    ("failure", "expected_cause"),
    (
        ("integrity", "restore verification failed"),
        ("isolation", "restore isolation verification failed"),
        ("containment", "credential containment failed"),
        ("notification", "notification assessment verification failed"),
        ("custody", "chain of custody verification failed"),
        ("rpo", "RPO objective exceeded"),
    ),
)
def test_restore_drill_fails_closed_for_injected_control_failures(
    tmp_path: Path,
    failure: str,
    expected_cause: str,
) -> None:
    """Every claimed control blocks success when its verification is injected false."""
    report_path = tmp_path / f"incident-drill-{failure}.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(DRILL_SCRIPT),
            "--report",
            str(report_path),
            "--inject-failure",
            failure,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode != 0
    report: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert expected_cause in report["simulation"]["failures"]


def test_postgres_drill_measures_objectives_and_binds_persistent_artifacts(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "postgres-drill.json"
    completed = subprocess.run(
        [sys.executable, str(POSTGRES_DRILL_SCRIPT), "--report", str(report_path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    report: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["image"]["reference"].startswith("postgres:17-alpine@sha256:")
    assert report["image"]["verified"] is True
    assert report["recovery"]["source_contains_controlled_change"] is True
    assert report["recovery"]["restored_contains_controlled_change"] is False
    checkpoint = datetime.fromisoformat(report["recovery_checkpoint_at"])
    change = datetime.fromisoformat(report["recovery"]["controlled_change_at"])
    assert report["timings_seconds"]["rpo_observed"] == pytest.approx(
        (change - checkpoint).total_seconds(), abs=0.000001
    )
    assert (
        report["timings_seconds"]["rto_observed"] <= report["objectives_seconds"]["rto"]
    )
    assert (
        report["timings_seconds"]["rpo_observed"] <= report["objectives_seconds"]["rpo"]
    )
    artifact_path = Path(report["artifact"]["locator"])
    manifest_path = Path(report["manifest"]["locator"])
    assert artifact_path.exists()
    assert manifest_path.exists()
    assert (
        hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        == report["digests"]["artifact_sha256"]
    )
    assert (
        hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        == report["digests"]["manifest_sha256"]
    )
    assert (
        report["digests"]["script_sha256"]
        == hashlib.sha256(POSTGRES_DRILL_SCRIPT.read_bytes()).hexdigest()
    )
    for digest in report["digests"].values():
        assert len(digest) == 64


def test_postgres_drill_fails_closed_when_rpo_objective_is_exceeded(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "postgres-rpo-failed.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(POSTGRES_DRILL_SCRIPT),
            "--report",
            str(report_path),
            "--rpo-objective-seconds",
            "0",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode != 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert "RPO objective exceeded" in report["failures"]
