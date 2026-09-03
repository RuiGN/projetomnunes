#!/usr/bin/env python3
"""Run an isolated encrypted PostgreSQL backup/restore exercise with synthetic data."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet

IMAGE_DIGEST = "18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73"
IMAGE = f"postgres:17-alpine@sha256:{IMAGE_DIGEST}"
RTO_OBJECTIVE_SECONDS = 60.0
RPO_OBJECTIVE_SECONDS = 300.0
CONTROLLED_SUBJECT = "synthetic-subject-post-checkpoint"


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _run(
    command: list[str],
    *,
    input_data: bytes | None = None,
    capture: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        input=input_data,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=True,
    )


def _docker_exec(name: str, *command: str, input_data: bytes | None = None) -> bytes:
    return _run(
        ["docker", "exec", "-i", name, *command],
        input_data=input_data,
    ).stdout


def _wait_ready(name: str) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", name, "pg_isready", "-U", "postgres"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.25)
    raise RuntimeError("Synthetic PostgreSQL container did not become ready.")


def _scalar(name: str, sql: str) -> str:
    output = _docker_exec(
        name,
        "psql",
        "-U",
        "postgres",
        "-d",
        "postgres",
        "-Atqc",
        sql,
    )
    return output.decode("utf-8").strip()


def run_drill(
    report_path: Path,
    *,
    inject_failure: str | None = None,
    rto_objective_seconds: float = RTO_OBJECTIVE_SECONDS,
    rpo_objective_seconds: float = RPO_OBJECTIVE_SECONDS,
) -> dict[str, object]:
    """Create, encrypt, persist, restore, and verify a PostgreSQL backup."""
    started_at = datetime.now(UTC)
    started = time.monotonic()
    suffix = uuid4().hex[:12]
    network = f"privacy-restore-{suffix}"
    source = f"privacy-source-{suffix}"
    target = f"privacy-target-{suffix}"
    password = secrets.token_urlsafe(24)
    cleanup_commands = [
        ["docker", "rm", "-f", source],
        ["docker", "rm", "-f", target],
        ["docker", "network", "rm", network],
    ]

    try:
        _run(["docker", "network", "create", "--internal", network])
        for name in (source, target):
            _run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--network",
                    network,
                    "--tmpfs",
                    "/var/lib/postgresql/data:rw,noexec,nosuid,size=256m",
                    "-e",
                    f"POSTGRES_PASSWORD={password}",
                    IMAGE,
                ]
            )
            _wait_ready(name)

        image_inspect = json.loads(
            _run(["docker", "image", "inspect", IMAGE]).stdout.decode("utf-8")
        )[0]
        image_verified = any(
            reference.endswith(f"@sha256:{IMAGE_DIGEST}")
            for reference in image_inspect.get("RepoDigests", [])
        )

        source_sql = b"""
CREATE TABLE synthetic_records (
    tenant_key text NOT NULL,
    subject_key text PRIMARY KEY,
    status text NOT NULL
);
INSERT INTO synthetic_records VALUES
('tenant-demo-a', 'synthetic-subject-001', 'active'),
('tenant-demo-a', 'synthetic-subject-002', 'inactive'),
('tenant-demo-b', 'synthetic-subject-003', 'active');
ALTER TABLE synthetic_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE synthetic_records FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON synthetic_records
USING (tenant_key = current_setting('app.tenant_key', true));
"""
        _docker_exec(
            source,
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "postgres",
            input_data=source_sql,
        )
        source_count = int(_scalar(source, "SELECT count(*) FROM synthetic_records"))
        plaintext_backup = _docker_exec(
            source,
            "pg_dump",
            "-U",
            "postgres",
            "--no-owner",
            "--no-privileges",
            "postgres",
        )
        plaintext_digest = _digest(plaintext_backup)
        recovery_checkpoint_at = datetime.now(UTC)
        _docker_exec(
            source,
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "postgres",
            input_data=(
                "INSERT INTO synthetic_records VALUES "
                f"('tenant-demo-a', '{CONTROLLED_SUBJECT}', "
                "'controlled-post-checkpoint');"
            ).encode(),
        )
        controlled_change_at = datetime.now(UTC)
        source_contains_controlled_change = (
            int(
                _scalar(
                    source,
                    "SELECT count(*) FROM synthetic_records "
                    f"WHERE subject_key='{CONTROLLED_SUBJECT}'",
                )
            )
            == 1
        )

        report_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        ciphertext = Fernet(key).encrypt(plaintext_backup)
        artifact_path = report_path.with_name(
            f"{report_path.stem}-backup.json"
        ).resolve()
        artifact_payload = (
            json.dumps(
                {
                    "schema_version": 1,
                    "algorithm": "Fernet (AES-128-CBC + HMAC-SHA256)",
                    "ciphertext": ciphertext.decode("ascii"),
                },
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        artifact_path.write_bytes(artifact_payload)
        artifact_path.chmod(0o600)
        artifact_digest = _digest(artifact_payload)
        script_digest = _digest(Path(__file__).read_bytes())
        manifest = {
            "created_at": recovery_checkpoint_at.isoformat(),
            "artifact_sha256": artifact_digest,
            "ciphertext_sha256": _digest(ciphertext),
            "source_sha256": plaintext_digest,
            "script_sha256": script_digest,
            "image_sha256": IMAGE_DIGEST,
            "source_record_count": source_count,
        }
        manifest_path = report_path.with_name(
            f"{report_path.stem}-manifest.json"
        ).resolve()
        manifest_payload = json.dumps(manifest, sort_keys=True).encode("utf-8") + b"\n"
        manifest_path.write_bytes(manifest_payload)
        manifest_path.chmod(0o600)
        manifest_digest = _digest(manifest_payload)

        restore_started = time.monotonic()
        stored_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stored_artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        stored_ciphertext = stored_artifact["ciphertext"].encode("ascii")
        ciphertext_verified = (
            _digest(artifact_path.read_bytes()) == stored_manifest["artifact_sha256"]
            and _digest(stored_ciphertext) == stored_manifest["ciphertext_sha256"]
        )
        restored_sql = Fernet(key).decrypt(stored_ciphertext)
        plaintext_verified = _digest(restored_sql) == stored_manifest["source_sha256"]
        with tempfile.TemporaryDirectory(prefix="postgres-restore-drill-") as temp_dir:
            restored_path = Path(temp_dir) / "postgres.sql"
            restored_path.write_bytes(restored_sql)
            restored_path.chmod(0o600)
            _docker_exec(
                target,
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                "postgres",
                input_data=restored_path.read_bytes(),
            )

        _docker_exec(
            target,
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "postgres",
            input_data=(
                b"CREATE ROLE tenant_reader; "
                b"GRANT SELECT ON synthetic_records TO tenant_reader;"
            ),
        )
        target_count = int(_scalar(target, "SELECT count(*) FROM synthetic_records"))
        scoped_count = int(
            _scalar(
                target,
                "SET ROLE tenant_reader; SET app.tenant_key='tenant-demo-a'; "
                "SELECT count(*) FROM synthetic_records;",
            )
        )
        cross_tenant_count = int(
            _scalar(
                target,
                "SET ROLE tenant_reader; SET app.tenant_key='tenant-demo-a'; "
                "SELECT count(*) FROM synthetic_records "
                "WHERE subject_key='synthetic-subject-003';",
            )
        )
        restored_contains_controlled_change = (
            int(
                _scalar(
                    target,
                    "SELECT count(*) FROM synthetic_records "
                    f"WHERE subject_key='{CONTROLLED_SUBJECT}'",
                )
            )
            == 1
        )
        target_inspect = json.loads(
            _run(["docker", "inspect", target]).stdout.decode("utf-8")
        )[0]
        network_inspect = json.loads(
            _run(["docker", "network", "inspect", network]).stdout.decode("utf-8")
        )[0]
        ports = target_inspect["NetworkSettings"].get("Ports") or {}
        published_ports = any(binding for binding in ports.values() if binding)
        network_attached = network in target_inspect["NetworkSettings"]["Networks"]
        internal_network = bool(network_inspect["Internal"])
        ephemeral_database = (
            target_inspect["HostConfig"]["Tmpfs"].get("/var/lib/postgresql/data")
            is not None
        )
        isolated_network = (
            network_attached
            and internal_network
            and not published_ports
            and ephemeral_database
        )
        rto_observed = time.monotonic() - restore_started
        rpo_observed = max(
            (controlled_change_at - recovery_checkpoint_at).total_seconds(),
            0.000001,
        )
        if inject_failure == "rto":
            rto_observed = rto_objective_seconds + 1.0
        elif inject_failure == "rpo":
            rpo_observed = rpo_objective_seconds + 1.0
        elif inject_failure == "image":
            image_verified = False
        elif inject_failure == "artifact":
            ciphertext_verified = False
        rto_within_objective = rto_observed <= rto_objective_seconds
        rpo_within_objective = rpo_observed <= rpo_objective_seconds
        passed = (
            ciphertext_verified
            and plaintext_verified
            and source_count == target_count == 3
            and scoped_count == 2
            and cross_tenant_count == 0
            and isolated_network
            and image_verified
            and source_contains_controlled_change
            and not restored_contains_controlled_change
            and rto_within_objective
            and rpo_within_objective
        )
        report: dict[str, object] = {
            "schema_version": 2,
            "status": "passed" if passed else "failed",
            "data_classification": "synthetic-only",
            "started_at": started_at.isoformat(),
            "recovery_checkpoint_at": recovery_checkpoint_at.isoformat(),
            "duration_seconds": round(time.monotonic() - started, 6),
            "objectives_seconds": {
                "rto": rto_objective_seconds,
                "rpo": rpo_objective_seconds,
            },
            "timings_seconds": {
                "rto_observed": round(rto_observed, 6),
                "rpo_observed": round(rpo_observed, 6),
            },
            "recovery": {
                "controlled_change_at": controlled_change_at.isoformat(),
                "controlled_change_subject_key": CONTROLLED_SUBJECT,
                "source_contains_controlled_change": source_contains_controlled_change,
                "restored_contains_controlled_change": (
                    restored_contains_controlled_change
                ),
                "rpo_calculation": "controlled_change_at - recovery_checkpoint_at",
                "rto_within_objective": rto_within_objective,
                "rpo_within_objective": rpo_within_objective,
            },
            "image": {
                "reference": IMAGE,
                "sha256": IMAGE_DIGEST,
                "verified": image_verified,
            },
            "artifact": {
                "locator": str(artifact_path),
                "encrypted": True,
                "authenticated": True,
            },
            "manifest": {"locator": str(manifest_path)},
            "digests": {
                "artifact_sha256": artifact_digest,
                "manifest_sha256": manifest_digest,
                "script_sha256": script_digest,
                "source_sha256": plaintext_digest,
                "image_sha256": IMAGE_DIGEST,
            },
            "failures": [
                name
                for name, verified in (
                    ("backup artifact verification failed", ciphertext_verified),
                    ("backup plaintext verification failed", plaintext_verified),
                    ("container image digest verification failed", image_verified),
                    (
                        "controlled source mutation missing",
                        source_contains_controlled_change,
                    ),
                    (
                        "controlled mutation unexpectedly restored",
                        not restored_contains_controlled_change,
                    ),
                    ("RTO objective exceeded", rto_within_objective),
                    ("RPO objective exceeded", rpo_within_objective),
                    ("restore isolation verification failed", isolated_network),
                )
                if not verified
            ],
            "database": {
                "engine": "PostgreSQL 17",
                "source_record_count": source_count,
                "restored_record_count": target_count,
                "tenant_a_visible_count": scoped_count,
                "cross_tenant_visible_count": cross_tenant_count,
            },
            "backup": {
                "encrypted": True,
                "persisted_before_restore": True,
                "ciphertext_verified": ciphertext_verified,
                "plaintext_verified": plaintext_verified,
                "key_persisted": False,
            },
            "isolation": {
                "internal_network": internal_network and network_attached,
                "published_ports": published_ports,
                "ephemeral_tmpfs_databases": ephemeral_database,
                "distinct_source_and_target": source != target,
            },
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report
    finally:
        for command in cleanup_commands:
            subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument(
        "--inject-failure",
        choices=("artifact", "image", "rto", "rpo"),
    )
    parser.add_argument(
        "--rto-objective-seconds",
        type=float,
        default=RTO_OBJECTIVE_SECONDS,
    )
    parser.add_argument(
        "--rpo-objective-seconds",
        type=float,
        default=RPO_OBJECTIVE_SECONDS,
    )
    arguments = parser.parse_args()
    report = run_drill(
        arguments.report,
        inject_failure=arguments.inject_failure,
        rto_objective_seconds=arguments.rto_objective_seconds,
        rpo_objective_seconds=arguments.rpo_objective_seconds,
    )
    print(json.dumps({"report": str(arguments.report), "status": report["status"]}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
