"""Validate the versioned CFP/CRP-02 regulatory compliance matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = PROJECT_ROOT / "docs" / "compliance" / "cfp-crp02-matrix.json"
PRD_PATH = PROJECT_ROOT / "PRD.md"
MAX_SOURCE_AGE_DAYS = 180
REQUIRED_ACT_FIELDS = {
    "id",
    "title",
    "issuer",
    "jurisdiction",
    "source_url",
    "effective_status",
    "effective_from",
    "history",
    "last_verified_at",
}
REQUIRED_OBLIGATION_FIELDS = {
    "id",
    "act_id",
    "provision",
    "effective_from",
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
REQUIRED_ACCEPTANCE_ROLES = {"clinical", "legal_regulatory"}
ALLOWED_ACCEPTANCE_STATES = {"pending", "accepted", "rejected", "expired"}
AFFIRMATIVE_DECISIONS = {
    "accepted",
    "approved",
    "aceito",
    "aceita",
    "aprovado",
    "aprovada",
}
PRD_TASK_PATTERN = re.compile(
    r"^\s*-\s+\[[ xX]\]\s+\*\*(8(?:\.\d+)+)(?:\*\*|\s+—)",
    re.MULTILINE,
)


class MatrixValidationError(ValueError):
    """Collect a fail-closed matrix validation error."""


def _nonempty(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value) and all(_nonempty(item) for item in value)
    if isinstance(value, dict):
        return bool(value)
    return value is not None


def _repository_reference_exists(value: object) -> bool:
    if not isinstance(value, str):
        return False
    relative_path = value.split("#", maxsplit=1)[0]
    candidate = (PROJECT_ROOT / relative_path).resolve()
    return candidate.is_relative_to(PROJECT_ROOT) and candidate.is_file()


def _iso_date(value: object, *, field: str) -> date:
    if not isinstance(value, str):
        raise MatrixValidationError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise MatrixValidationError(f"{field} must be an ISO date") from error


def _iso_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise MatrixValidationError(f"{field} must be an ISO timestamp")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MatrixValidationError(f"{field} must be an ISO timestamp") from error
    if timestamp.tzinfo is None:
        raise MatrixValidationError(f"{field} must include a timezone")
    return timestamp


def validate_matrix(matrix: dict[str, Any], *, today: date | None = None) -> list[str]:
    """Return every completeness or release-integrity violation."""
    errors: list[str] = []
    current_date = today or date.today()
    try:
        prd_task_ids = set(
            PRD_TASK_PATTERN.findall(PRD_PATH.read_text(encoding="utf-8"))
        )
    except OSError as error:
        errors.append(f"PRD task registry is unreadable: {error}")
        prd_task_ids = set()

    for field in (
        "schema_version",
        "version",
        "jurisdiction",
        "last_reviewed_at",
        "review_policy",
    ):
        if not _nonempty(matrix.get(field)):
            errors.append(f"matrix.{field} is required")
    if matrix.get("schema_version") != 1:
        errors.append("matrix.schema_version must equal 1")
    try:
        matrix_reviewed_at = _iso_date(
            matrix.get("last_reviewed_at"), field="matrix.last_reviewed_at"
        )
        age = (current_date - matrix_reviewed_at).days
        if age < 0 or age > MAX_SOURCE_AGE_DAYS:
            errors.append("matrix.last_reviewed_at is stale or in the future")
    except MatrixValidationError as error:
        errors.append(str(error))

    acts = matrix.get("acts")
    if not isinstance(acts, list) or not acts:
        errors.append("matrix.acts must contain at least one normative source")
        acts = []
    act_ids: set[str] = set()
    for index, act in enumerate(acts):
        prefix = f"acts[{index}]"
        if not isinstance(act, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing = REQUIRED_ACT_FIELDS - act.keys()
        for field in sorted(missing):
            errors.append(f"{prefix}.{field} is required")
        for field in REQUIRED_ACT_FIELDS & act.keys():
            if not _nonempty(act[field]):
                errors.append(f"{prefix}.{field} cannot be empty")
        act_id = act.get("id")
        if isinstance(act_id, str):
            if act_id in act_ids:
                errors.append(f"duplicate act id: {act_id}")
            act_ids.add(act_id)
        if act.get("effective_status") not in {"effective", "partially_effective"}:
            errors.append(f"{prefix}.effective_status must be assessed as effective")
        try:
            verified_at = _iso_date(
                act.get("last_verified_at"), field=f"{prefix}.last_verified_at"
            )
            age = (current_date - verified_at).days
            if age < 0 or age > MAX_SOURCE_AGE_DAYS:
                errors.append(f"{prefix}.last_verified_at is stale or in the future")
        except MatrixValidationError as error:
            errors.append(str(error))

    obligations = matrix.get("obligations")
    if not isinstance(obligations, list) or not obligations:
        errors.append("matrix.obligations must contain at least one obligation")
        obligations = []
    obligation_ids: set[str] = set()
    referenced_acts: set[str] = set()
    for index, obligation in enumerate(obligations):
        prefix = f"obligations[{index}]"
        if not isinstance(obligation, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing = REQUIRED_OBLIGATION_FIELDS - obligation.keys()
        for field in sorted(missing):
            errors.append(f"{prefix}.{field} is required")
        for field in REQUIRED_OBLIGATION_FIELDS & obligation.keys():
            if not _nonempty(obligation[field]):
                errors.append(f"{prefix}.{field} cannot be empty")
        evidence_references = obligation.get("evidence", [])
        if isinstance(evidence_references, list):
            for reference in evidence_references:
                if not _repository_reference_exists(reference):
                    errors.append(
                        f"{prefix}.evidence reference does not exist: {reference}"
                    )
        verification_references = obligation.get("verification", [])
        if isinstance(verification_references, list):
            for reference in verification_references:
                if not _repository_reference_exists(reference):
                    errors.append(
                        f"{prefix}.verification reference does not exist: {reference}"
                    )
        obligation_id = obligation.get("id")
        if isinstance(obligation_id, str):
            if obligation_id in obligation_ids:
                errors.append(f"duplicate obligation id: {obligation_id}")
            obligation_ids.add(obligation_id)
        act_id = obligation.get("act_id")
        if isinstance(act_id, str):
            referenced_acts.add(act_id)
            if act_id not in act_ids:
                errors.append(f"{prefix}.act_id references an unknown act")
        if obligation.get("effective_status") not in {
            "effective",
            "partially_effective",
        }:
            errors.append(f"{prefix}.effective_status must be assessed as effective")
        try:
            effective_from = _iso_date(
                obligation.get("effective_from"),
                field=f"{prefix}.effective_from",
            )
            if effective_from > current_date:
                errors.append(f"{prefix}.effective_from cannot be in the future")
        except MatrixValidationError as error:
            errors.append(str(error))
        backlog_tasks = obligation.get("backlog_tasks")
        if isinstance(backlog_tasks, list):
            for task_id in backlog_tasks:
                if not isinstance(task_id, str) or task_id not in prd_task_ids:
                    errors.append(
                        f"{prefix}.backlog_tasks references unknown PRD id: {task_id}"
                    )
        owners = obligation.get("acceptance_owners")
        if not isinstance(owners, list) or not set(owners) >= REQUIRED_ACCEPTANCE_ROLES:
            errors.append(
                f"{prefix}.acceptance_owners must include clinical and legal_regulatory"
            )
        try:
            reviewed_at = _iso_date(
                obligation.get("last_reviewed_at"),
                field=f"{prefix}.last_reviewed_at",
            )
            age = (current_date - reviewed_at).days
            if age < 0 or age > MAX_SOURCE_AGE_DAYS:
                errors.append(f"{prefix}.last_reviewed_at is stale or in the future")
        except MatrixValidationError as error:
            errors.append(str(error))

    unreferenced = act_ids - referenced_acts
    if unreferenced:
        errors.append(
            f"acts without mapped obligations: {', '.join(sorted(unreferenced))}"
        )

    acceptances = matrix.get("acceptances")
    if not isinstance(acceptances, list):
        errors.append("matrix.acceptances must be a list")
        acceptances = []
    acceptance_by_role: dict[str, dict[str, Any]] = {}
    for index, acceptance in enumerate(acceptances):
        prefix = f"acceptances[{index}]"
        if not isinstance(acceptance, dict):
            errors.append(f"{prefix} must be an object")
            continue
        role = acceptance.get("role")
        status = acceptance.get("status")
        if role not in REQUIRED_ACCEPTANCE_ROLES:
            errors.append(f"{prefix}.role is unsupported")
            continue
        if role in acceptance_by_role:
            errors.append(f"duplicate acceptance role: {role}")
        acceptance_by_role[role] = acceptance
        if status not in ALLOWED_ACCEPTANCE_STATES:
            errors.append(f"{prefix}.status is unsupported")
        if status == "accepted":
            for field in (
                "approver",
                "accepted_at",
                "scope",
                "decision",
                "review_due_at",
                "matrix_version",
                "evidence_path",
                "evidence_sha256",
            ):
                if not _nonempty(acceptance.get(field)):
                    errors.append(f"{prefix}.{field} is required for accepted status")
            if acceptance.get("matrix_version") != matrix.get("version"):
                errors.append(f"{prefix}.matrix_version must match matrix.version")
            release_decision = matrix.get("release_decision")
            release_scope = (
                release_decision.get("scope")
                if isinstance(release_decision, dict)
                else None
            )
            if acceptance.get("scope") != release_scope:
                errors.append(f"{prefix}.scope must match release_decision.scope")
            acceptance_decision = acceptance.get("decision")
            if (
                not isinstance(acceptance_decision, str)
                or acceptance_decision.strip().casefold() not in AFFIRMATIVE_DECISIONS
            ):
                errors.append(f"{prefix}.decision must be affirmative")
            evidence_value = acceptance.get("evidence_path")
            if isinstance(evidence_value, str):
                evidence_path = (PROJECT_ROOT / evidence_value).resolve()
                if not evidence_path.is_relative_to(PROJECT_ROOT):
                    errors.append(f"{prefix}.evidence_path must stay inside repository")
                elif not evidence_path.is_file():
                    errors.append(f"{prefix}.evidence_path does not exist")
                elif hashlib.sha256(
                    evidence_path.read_bytes()
                ).hexdigest() != acceptance.get("evidence_sha256"):
                    errors.append(
                        f"{prefix}.evidence_sha256 does not match evidence file"
                    )
            try:
                accepted_at = _iso_timestamp(
                    acceptance.get("accepted_at"), field=f"{prefix}.accepted_at"
                )
                if accepted_at > datetime.now(tz=accepted_at.tzinfo):
                    errors.append(f"{prefix}.accepted_at cannot be in the future")
            except MatrixValidationError as error:
                errors.append(str(error))
            try:
                if (
                    _iso_date(
                        acceptance.get("review_due_at"), field=f"{prefix}.review_due_at"
                    )
                    < current_date
                ):
                    errors.append(f"{prefix}.review_due_at has expired")
            except MatrixValidationError as error:
                errors.append(str(error))
    missing_roles = REQUIRED_ACCEPTANCE_ROLES - acceptance_by_role.keys()
    if missing_roles:
        errors.append(f"missing acceptance roles: {', '.join(sorted(missing_roles))}")

    decision = matrix.get("release_decision")
    if not isinstance(decision, dict):
        errors.append("matrix.release_decision must be an object")
    else:
        status = decision.get("status")
        if status not in {"blocked", "approved"}:
            errors.append("release_decision.status must be blocked or approved")
        for field in ("scope", "reason", "next_review_at"):
            if not _nonempty(decision.get(field)):
                errors.append(f"release_decision.{field} is required")
        try:
            next_review_at = _iso_date(
                decision.get("next_review_at"),
                field="release_decision.next_review_at",
            )
            if next_review_at < current_date:
                errors.append("release_decision.next_review_at has expired")
        except MatrixValidationError as error:
            errors.append(str(error))
        approvals_current = all(
            acceptance_by_role.get(role, {}).get("status") == "accepted"
            for role in REQUIRED_ACCEPTANCE_ROLES
        )
        if status == "approved" and not approvals_current:
            errors.append(
                "regulated release requires current clinical and "
                "legal/regulatory approvals"
            )
        if status == "blocked" and approvals_current:
            errors.append(
                "release decision is blocked despite current required approvals"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--require-release-approval", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        matrix = json.loads(arguments.matrix.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exception:
        print(f"regulatory matrix unreadable: {exception}", file=sys.stderr)
        return 2
    if not isinstance(matrix, dict):
        print("regulatory matrix root must be an object", file=sys.stderr)
        return 2

    errors = validate_matrix(matrix)
    if errors:
        for error in errors:
            print(f"regulatory matrix error: {error}", file=sys.stderr)
        return 1
    status = matrix["release_decision"]["status"]
    if arguments.require_release_approval and status != "approved":
        print(
            "regulated release blocked: required human approvals are not current",
            file=sys.stderr,
        )
        return 3
    print(f"regulatory matrix complete; regulated release {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
