"""Tests for anonymization transforms and re-identification attacks (PRD 8.19.5)."""

from datetime import date

from analytics.anonymization import (
    detect_differencing_attack,
    detect_linkage_risk,
    detect_singling_out_risk,
    generalize_age,
    generalize_date_to_quarter,
    generalize_postal_code,
)


def test_quasi_identifier_generalization() -> None:
    # Age generalization to 10-year bands
    assert generalize_age(24) == "20-29 anos"
    assert generalize_age(29) == "20-29 anos"
    assert generalize_age(30) == "30-39 anos"
    assert generalize_age(45) == "40-49 anos"

    # Postal code to first 5 digits (municipality macro-band)
    assert generalize_postal_code("01310-100") == "01310-***"
    assert generalize_postal_code("04538133") == "04538-***"

    # Date to calendar quarter
    assert generalize_date_to_quarter(date(2026, 1, 15)) == "2026-Q1"
    assert generalize_date_to_quarter(date(2026, 5, 20)) == "2026-Q2"
    assert generalize_date_to_quarter(date(2026, 8, 1)) == "2026-Q3"
    assert generalize_date_to_quarter(date(2026, 12, 31)) == "2026-Q4"


def test_detect_singling_out_risk() -> None:
    # Dataset where one combination has fewer than k=5 records
    records_with_risk = [
        {"age_band": "20-29", "gender": "F"},
        {"age_band": "20-29", "gender": "F"},
        {"age_band": "20-29", "gender": "F"},
        {"age_band": "20-29", "gender": "F"},
        {"age_band": "20-29", "gender": "F"},  # count = 5 for (20-29, F)
        {"age_band": "50-59", "gender": "M"},  # count = 1 -> singling out!
    ]
    has_risk = detect_singling_out_risk(
        records_with_risk, quasi_identifiers=["age_band", "gender"], k_threshold=5
    )
    assert has_risk is True

    # Safe dataset where every class has at least k=3 records
    safe_records = [
        {"age_band": "20-29", "gender": "F"},
        {"age_band": "20-29", "gender": "F"},
        {"age_band": "20-29", "gender": "F"},
        {"age_band": "30-39", "gender": "M"},
        {"age_band": "30-39", "gender": "M"},
        {"age_band": "30-39", "gender": "M"},
    ]
    assert detect_singling_out_risk(
        safe_records, quasi_identifiers=["age_band", "gender"], k_threshold=3
    ) is False


def test_detect_linkage_risk() -> None:
    target_dataset = [
        {"id": "rec_1", "age_band": "20-29", "cep_prefix": "01310"},
        {"id": "rec_2", "age_band": "30-39", "cep_prefix": "04538"},
    ]
    # Auxiliary dataset with names where rec_1 can be uniquely linked
    auxiliary_dataset = [
        {"name": "Fulano", "age_band": "20-29", "cep_prefix": "01310"},
        {"name": "Ciclano", "age_band": "40-49", "cep_prefix": "20020"},
    ]
    linked = detect_linkage_risk(
        target_dataset, auxiliary_dataset, linking_keys=["age_band", "cep_prefix"]
    )
    assert len(linked) == 1
    assert linked[0]["id"] == "rec_1"


def test_detect_differencing_attack() -> None:
    query_a_ids = {"p1", "p2", "p3", "p4", "p5"}
    query_b_ids = {"p1", "p2", "p3", "p4", "p5", "p6"}

    # Difference is exactly 1 individual (p6), allowing deduction of p6's attributes
    is_attack = detect_differencing_attack(query_a_ids, query_b_ids, threshold=1)
    assert is_attack is True

    # Identical queries have difference 0 (not an attack)
    assert detect_differencing_attack(query_a_ids, query_a_ids, threshold=1) is False

    # Queries differing by more than threshold are safe
    query_c_ids = {"p1", "p2", "p3", "p7", "p8", "p9"}
    assert detect_differencing_attack(query_a_ids, query_c_ids, threshold=1) is False
