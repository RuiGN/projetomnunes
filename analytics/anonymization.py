"""Anonymization transformations and attack detection suites (PRD 8.19.5)."""

from __future__ import annotations

from collections import Counter
from datetime import date
from enum import StrEnum
from typing import Any


class QuasiIdentifierType(StrEnum):
    """Classification of quasi-identifiers prone to linkage attacks (8.19.5.1)."""

    AGE = "age"
    POSTAL_CODE = "postal_code"
    GENDER = "gender"
    DATE = "date"


def generalize_age(age: int) -> str:
    """Generalize exact age into 10-year age bands to satisfy k-anonymity."""
    if age < 0:
        return "Desconhecido"
    lower = (age // 10) * 10
    upper = lower + 9
    return f"{lower}-{upper} anos"


def generalize_postal_code(postal_code: str) -> str:
    """Generalize Brazilian CEP to the first 5 digits (municipality/macro-region)."""
    digits = "".join(c for c in postal_code if c.isdigit())
    if len(digits) >= 5:
        return f"{digits[:5]}-***"
    return "*****-***"


def generalize_date_to_quarter(d: date) -> str:
    """Generalize specific date to calendar quarter to prevent temporal linkage."""
    quarter = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{quarter}"


def detect_singling_out_risk(
    records: list[dict[str, Any]],
    quasi_identifiers: list[str],
    k_threshold: int = 5,
) -> bool:
    """Evaluate k-anonymity; return True if ANY group has count < k (8.19.5.2)."""
    if not records:
        return False

    classes = Counter(
        tuple(record.get(qi) for qi in quasi_identifiers) for record in records
    )
    return any(count < k_threshold for count in classes.values())


def detect_linkage_risk(
    dataset: list[dict[str, Any]],
    auxiliary_dataset: list[dict[str, Any]],
    linking_keys: list[str],
) -> list[dict[str, Any]]:
    """Detect records uniquely linked between dataset and auxiliary source."""
    if not dataset or not auxiliary_dataset or not linking_keys:
        return []

    # Map auxiliary dataset tuples to count
    aux_keys = [tuple(item.get(k) for k in linking_keys) for item in auxiliary_dataset]
    aux_counts = Counter(aux_keys)
    unique_aux = {k for k, count in aux_counts.items() if count == 1}

    # Identify records that link to exactly 1 distinct auxiliary record
    linked: list[dict[str, Any]] = []
    for rec in dataset:
        key = tuple(rec.get(k) for k in linking_keys)
        if key in unique_aux:
            linked.append(rec)
    return linked


def detect_differencing_attack(
    query_a_ids: set[str],
    query_b_ids: set[str],
    threshold: int = 1,
) -> bool:
    """Detect differencing attack isolating an individual (diff <= threshold)."""
    difference = query_a_ids.symmetric_difference(query_b_ids)
    return 0 < len(difference) <= threshold
