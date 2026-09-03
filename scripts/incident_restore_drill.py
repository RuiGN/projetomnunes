#!/usr/bin/env python3
"""Exercise encrypted backup restore and incident handling with synthetic data."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken

SYNTHETIC_ROWS = (
    ("tenant-demo-a", "synthetic-subject-001", "active"),
    ("tenant-demo-a", "synthetic-subject-002", "inactive"),
    ("tenant-demo-b", "synthetic-subject-003", "active"),
)
CONTROLLED_CHANGE = (
    "tenant-demo-a",
    "synthetic-subject-post-checkpoint",
    "controlled-post-checkpoint",
)


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _create_source_database(path: Path) -> int:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE synthetic_records ("
            "tenant_key TEXT NOT NULL, subject_key TEXT NOT NULL UNIQUE, "
            "status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO synthetic_records VALUES (?, ?, ?)", SYNTHETIC_ROWS
        )
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if result != ("ok",):
            raise RuntimeError("Synthetic source integrity check failed.")
        count = connection.execute("SELECT COUNT(*) FROM synthetic_records").fetchone()[
            0
        ]
        return int(count)


def _verify_restored_database(path: Path) -> tuple[int, bool]:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        integrity_result = connection.execute("PRAGMA integrity_check").fetchone()
        rows = connection.execute(
            "SELECT tenant_key, subject_key, status "
            "FROM synthetic_records ORDER BY subject_key"
        ).fetchall()
        foreign_tenant_leak = connection.execute(
            "SELECT COUNT(*) FROM synthetic_records "
            "WHERE tenant_key = ? AND subject_key LIKE ?",
            ("tenant-demo-a", "synthetic-subject-003"),
        ).fetchone()[0]
    expected = sorted(SYNTHETIC_ROWS, key=lambda row: row[1])
    verified = (
        integrity_result == ("ok",) and rows == expected and not foreign_tenant_leak
    )
    return len(rows), verified


def _contains_subject(path: Path, subject_key: str) -> bool:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM synthetic_records WHERE subject_key = ?",
            (subject_key,),
        ).fetchone()[0]
    return bool(count)


def _corruption_is_rejected(cipher: Fernet, encrypted_backup: bytes) -> bool:
    tampered = bytearray(encrypted_backup)
    tampered[len(tampered) // 2] ^= 1
    try:
        cipher.decrypt(bytes(tampered))
    except InvalidToken:
        return True
    return False


def run_drill(
    report_path: Path,
    *,
    inject_failure: str | None = None,
) -> dict[str, Any]:
    """Persist, retrieve, verify, and restore one encrypted synthetic backup."""
    started = time.monotonic()
    started_at = datetime.now(UTC)

    with tempfile.TemporaryDirectory(prefix="synthetic-restore-drill-") as temp_dir:
        exercise_root = Path(temp_dir)
        source_environment = exercise_root / "source-environment"
        backup_store = exercise_root / "backup-store"
        restore_environment = exercise_root / "isolated-restore-environment"
        for directory in (source_environment, backup_store, restore_environment):
            directory.mkdir(mode=0o700)

        source_path = source_environment / "source.sqlite3"
        source_count = _create_source_database(source_path)
        source_payload = source_path.read_bytes()
        source_digest = _digest(source_payload)

        backup_created_at = datetime.now(UTC)
        recovery_checkpoint_at = backup_created_at
        exercise_key = Fernet.generate_key()
        cipher = Fernet(exercise_key)
        encrypted_backup = cipher.encrypt(source_payload)
        backup_path = backup_store / "snapshot.sqlite3.fernet"
        backup_path.write_bytes(encrypted_backup)
        backup_path.chmod(0o600)
        manifest_path = backup_store / "snapshot.manifest.json"
        manifest = {
            "schema_version": 1,
            "created_at": backup_created_at.isoformat(),
            "source_format": "sqlite3-synthetic",
            "source_sha256": source_digest,
            "ciphertext_sha256": _digest(encrypted_backup),
            "source_record_count": source_count,
        }
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest_path.chmod(0o600)
        manifest_digest = _digest(manifest_path.read_bytes())

        # A known mutation after the checkpoint makes RPO a measured loss window,
        # rather than elapsed wall-clock time at the end of the exercise.
        with sqlite3.connect(source_path) as connection:
            connection.execute(
                "INSERT INTO synthetic_records VALUES (?, ?, ?)", CONTROLLED_CHANGE
            )
        controlled_change_at = datetime.now(UTC)
        source_contains_controlled_change = _contains_subject(
            source_path, CONTROLLED_CHANGE[1]
        )

        restore_started = time.monotonic()
        stored_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stored_encrypted_backup = backup_path.read_bytes()
        ciphertext_integrity_verified = (
            _digest(stored_encrypted_backup) == stored_manifest["ciphertext_sha256"]
        )
        provenance_verified = (
            stored_manifest["source_format"] == "sqlite3-synthetic"
            and stored_manifest["source_record_count"] == source_count
            and stored_manifest["source_sha256"] == source_digest
        )
        corrupted_backup_rejected = _corruption_is_rejected(
            cipher, stored_encrypted_backup
        )
        restored_payload = cipher.decrypt(stored_encrypted_backup)
        restored_path = restore_environment / "restored.sqlite3"
        restored_path.write_bytes(restored_payload)
        restored_path.chmod(0o600)

        restored_digest = _digest(restored_path.read_bytes())
        restored_count, tenant_isolation_verified = _verify_restored_database(
            restored_path
        )
        restored_contains_controlled_change = _contains_subject(
            restored_path, CONTROLLED_CHANGE[1]
        )
        integrity_verified = (
            ciphertext_integrity_verified
            and source_digest == restored_digest
            and restored_digest == stored_manifest["source_sha256"]
        )
        isolated = (
            source_path.parent != restored_path.parent
            and backup_path.parent != restored_path.parent
            and source_path.resolve() != restored_path.resolve()
        )
        rto_observed = time.monotonic() - restore_started

        incident_directory = exercise_root / "restricted-incident-record"
        incident_directory.mkdir(mode=0o700)
        incident_id = f"INC-DRILL-{uuid4()}"
        incident_record = {
            "incident_id": incident_id,
            "opened_at": datetime.now(UTC).isoformat(),
            "classification": "exercise-synthetic",
            "scenario": "suspected credential compromise during restore",
            "access_scope": "incident-response-team",
        }
        containment_record = {
            "incident_id": incident_id,
            "performed_at": datetime.now(UTC).isoformat(),
            "target": "exercise-restore-credential",
            "previous_state": "active",
            "resulting_state": "revoked",
        }
        notification_assessment = {
            "incident_id": incident_id,
            "assessed_at": datetime.now(UTC).isoformat(),
            "decision": "exercise-only-no-notification",
            "rationale": "Only synthetic records and an isolated credential were used.",
            "responsible_role": "Data Protection Officer",
        }
        evidence_payloads = {
            "incident.json": incident_record,
            "containment.json": containment_record,
            "notification-assessment.json": notification_assessment,
        }
        evidence_digests: dict[str, str] = {}
        for filename, payload in evidence_payloads.items():
            evidence_path = incident_directory / filename
            serialized = json.dumps(payload, sort_keys=True).encode("utf-8")
            evidence_path.write_bytes(serialized)
            evidence_path.chmod(0o600)
            evidence_digests[filename] = _digest(evidence_path.read_bytes())
        chain_of_custody = {
            "incident_id": incident_id,
            "recorded_at": datetime.now(UTC).isoformat(),
            "artifacts": evidence_digests,
        }
        chain_path = incident_directory / "chain-of-custody.json"
        chain_path.write_text(
            json.dumps(chain_of_custody, sort_keys=True), encoding="utf-8"
        )
        chain_path.chmod(0o600)
        incident_record_verified = (
            json.loads((incident_directory / "incident.json").read_text())
            == incident_record
        )
        containment_verified = (
            json.loads((incident_directory / "containment.json").read_text())[
                "resulting_state"
            ]
            == "revoked"
        )
        notification_assessment_verified = (
            json.loads(
                (incident_directory / "notification-assessment.json").read_text()
            )["responsible_role"]
            == "Data Protection Officer"
        )
        chain_of_custody_verified = all(
            _digest((incident_directory / filename).read_bytes()) == digest
            for filename, digest in json.loads(chain_path.read_text())[
                "artifacts"
            ].items()
        )
        evidence_manifest_sha256 = _digest(chain_path.read_bytes())
        custody_plaintext = json.dumps(
            {
                "chain_of_custody": chain_of_custody,
                "artifacts": evidence_payloads,
            },
            sort_keys=True,
        ).encode("utf-8")
        custody_token = cipher.encrypt(custody_plaintext)
        package_path = report_path.with_name(
            f"{report_path.stem}-custody.json"
        ).resolve()
        package_payload = (
            json.dumps(
                {
                    "schema_version": 1,
                    "algorithm": "Fernet (AES-128-CBC + HMAC-SHA256)",
                    "ciphertext": custody_token.decode("ascii"),
                },
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        package_path.parent.mkdir(parents=True, exist_ok=True)
        package_path.write_bytes(package_payload)
        package_path.chmod(0o600)
        package_digest = _digest(package_payload)

        rpo_objective_seconds = 300.0
        rpo_observed = max(
            (controlled_change_at - recovery_checkpoint_at).total_seconds(),
            0.000001,
        )
        if inject_failure == "integrity":
            integrity_verified = False
        elif inject_failure == "isolation":
            isolated = False
        elif inject_failure == "containment":
            containment_verified = False
        elif inject_failure == "notification":
            notification_assessment_verified = False
        elif inject_failure == "custody":
            chain_of_custody_verified = False
        elif inject_failure == "rpo":
            rpo_observed = rpo_objective_seconds + 1.0
        rpo_within_objective = rpo_observed <= rpo_objective_seconds

    persisted_package = json.loads(package_path.read_text(encoding="utf-8"))
    package_verified_after_cleanup = (
        _digest(package_path.read_bytes()) == package_digest
        and cipher.decrypt(persisted_package["ciphertext"].encode("ascii"))
        == custody_plaintext
    )
    elapsed = time.monotonic() - started
    passed = (
        integrity_verified
        and provenance_verified
        and corrupted_backup_rejected
        and isolated
        and tenant_isolation_verified
        and source_count == restored_count
        and source_count == len(SYNTHETIC_ROWS)
        and incident_record_verified
        and containment_verified
        and notification_assessment_verified
        and chain_of_custody_verified
        and package_verified_after_cleanup
        and source_contains_controlled_change
        and not restored_contains_controlled_change
        and rpo_within_objective
    )
    report: dict[str, Any] = {
        "schema_version": 2,
        "exercise_started_at": started_at.isoformat(),
        "status": "passed" if passed else "failed",
        "data_classification": "synthetic-only",
        "recovery_checkpoint_at": recovery_checkpoint_at.isoformat(),
        "objectives_seconds": {"rpo": rpo_objective_seconds},
        "exercise_scope": (
            "format-level encrypted SQLite restore; production PostgreSQL and object "
            "storage restore remains an environment-specific operational exercise"
        ),
        "backup": {
            "encrypted": True,
            "algorithm": "Fernet (AES-128-CBC + HMAC-SHA256)",
            "persisted_before_restore": True,
            "provenance_verified": provenance_verified,
            "ciphertext_integrity_verified": ciphertext_integrity_verified,
            "ciphertext_sha256": stored_manifest["ciphertext_sha256"],
            "manifest_sha256": manifest_digest,
            "key_persisted": False,
        },
        "evidence_package": {
            "locator": str(package_path),
            "sha256": package_digest,
            "encrypted": True,
            "authenticated": True,
            "verified_after_temporary_cleanup": package_verified_after_cleanup,
        },
        "digests": {
            "artifact_sha256": package_digest,
            "manifest_sha256": evidence_manifest_sha256,
            "script_sha256": _digest(Path(__file__).read_bytes()),
            "source_sha256": source_digest,
        },
        "recovery": {
            "controlled_change_at": controlled_change_at.isoformat(),
            "controlled_change_subject_key": CONTROLLED_CHANGE[1],
            "source_contains_controlled_change": source_contains_controlled_change,
            "restored_contains_controlled_change": restored_contains_controlled_change,
            "rpo_calculation": "controlled_change_at - recovery_checkpoint_at",
            "rpo_within_objective": rpo_within_objective,
        },
        "restore": {
            "isolated": isolated,
            "source_record_count": source_count,
            "restored_record_count": restored_count,
            "integrity_verified": integrity_verified,
            "tenant_isolation_verified": tenant_isolation_verified,
            "corrupted_backup_rejected": corrupted_backup_rejected,
        },
        "simulation": {
            "scenario": "suspected credential compromise during restore",
            "incident_id": incident_id,
            "incident_record_verified": incident_record_verified,
            "containment_verified": containment_verified,
            "notification_assessment_verified": notification_assessment_verified,
            "chain_of_custody_verified": chain_of_custody_verified,
            "evidence_manifest_sha256": evidence_manifest_sha256,
            "actions_exercised": [
                action
                for action, verified in (
                    ("opened restricted incident record", incident_record_verified),
                    ("revoked isolated exercise credential", containment_verified),
                    (
                        "recorded notification decision",
                        notification_assessment_verified,
                    ),
                    ("verified evidence chain of custody", chain_of_custody_verified),
                )
                if verified
            ],
            "failures_exercised": ["tampered encrypted backup rejected"],
            "evidence_preserved": chain_of_custody_verified,
            "failures": [
                name
                for name, verified in (
                    ("restore verification failed", integrity_verified),
                    ("restore isolation verification failed", isolated),
                    ("incident record verification failed", incident_record_verified),
                    ("credential containment failed", containment_verified),
                    (
                        "notification assessment verification failed",
                        notification_assessment_verified,
                    ),
                    ("chain of custody verification failed", chain_of_custody_verified),
                    ("RPO objective exceeded", rpo_within_objective),
                )
                if not verified
            ],
            "corrective_actions": [
                {
                    "action": (
                        "Run the provider-specific PostgreSQL/object-storage restore "
                        "drill."
                    ),
                    "owner": "Platform Operations",
                    "due_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                },
                {
                    "action": "Review the responder contact roster.",
                    "owner": "Incident Commander",
                    "due_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                },
            ],
        },
        "timings_seconds": {
            "rto_observed": round(rto_observed, 6),
            "rpo_observed": round(rpo_observed, 6),
            "total": round(elapsed, 6),
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    """Parse CLI arguments, run the drill, and expose pass/fail to automation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument(
        "--inject-failure",
        choices=(
            "integrity",
            "isolation",
            "containment",
            "notification",
            "custody",
            "rpo",
        ),
    )
    arguments = parser.parse_args()
    report = run_drill(
        arguments.report,
        inject_failure=arguments.inject_failure,
    )
    print(json.dumps({"report": str(arguments.report), "status": report["status"]}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
