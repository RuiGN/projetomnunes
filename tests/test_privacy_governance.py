"""Executable acceptance checks for the MVP privacy governance artifacts."""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRIVACY_ROOT = PROJECT_ROOT / "docs" / "privacy"


@pytest.mark.parametrize(
    ("relative_path", "required_terms"),
    [
        (
            "data-inventory.md",
            (
                "Identity and registration data",
                "Professional data",
                "Professional regulatory evidence",
                "Clinic regulatory evidence",
                "TDIC service agreement evidence",
                "Psychological record data",
                "Restricted psychological assessment material",
                "Emergency and protection action data",
                "Contact data",
                "Consent evidence",
                "Usage and security data",
                "Declared clinical data",
                "Sensitive personal data",
                "CFP",
                "CRP",
            ),
        ),
        (
            "processing-register.md",
            (
                "Purpose",
                "Necessity",
                "Legal basis",
                "Controller",
                "Processor",
                "Recipients",
                "Retention",
            ),
        ),
        (
            "data-flows.md",
            (
                "Collection",
                "Storage",
                "Access",
                "Export",
                "Sharing",
                "Disposal",
                "Supplier",
                "Professional eligibility verification",
                "Clinic regulatory evidence",
                "TDIC service agreement",
                "Psychological record",
                "Restricted assessment material",
                "Emergency and protection action",
                "Psychology Council inspection",
            ),
        ),
        (
            "feature-privacy-checklist.md",
            (
                "Data minimization",
                "No implicit secondary use",
                "Sensitive fields require justification",
                "Tenant isolation",
                "Logs and telemetry",
                "Retention and disposal",
                "Professional and regulatory eligibility",
                "Regulated release gate",
                "Psychological record",
                "Restricted assessment material",
                "Legal/regulatory approver",
                "blocking decision",
            ),
        ),
    ],
)
def test_privacy_artifact_covers_required_controls(
    relative_path: str,
    required_terms: tuple[str, ...],
) -> None:
    """Each versioned artifact remains complete enough to gate MVP changes."""
    document = (PRIVACY_ROOT / relative_path).read_text(encoding="utf-8")

    for term in required_terms:
        assert term in document


def test_processing_register_covers_every_mvp_data_category() -> None:
    """The ROPA links each inventoried MVP category to a processing record."""
    inventory = (PRIVACY_ROOT / "data-inventory.md").read_text(encoding="utf-8")
    register = (PRIVACY_ROOT / "processing-register.md").read_text(encoding="utf-8")
    category_ids = {
        line.split("`", 2)[1]
        for line in inventory.splitlines()
        if line.startswith("| `")
    }

    assert category_ids
    for category_id in category_ids:
        assert f"`{category_id}`" in register
