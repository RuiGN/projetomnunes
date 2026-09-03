"""Typed purpose catalog and consent authorization classifications."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.policies import AuthorizationPolicy as AuthorizationPolicy


class PurposeClassification(StrEnum):
    """How a processing purpose relates to an explicit manifestation."""

    BASIC_RIGHT = "basic_right"
    CONTRACTUAL_REQUIREMENT = "contractual_requirement"
    OPTIONAL_CONSENT = "optional_consent"


class ConsentPurpose(StrEnum):
    """Closed catalog of purposes understood by the consents domain."""

    TERMS_OF_USE = "terms_of_use"
    CLINICAL_LIMITS = "clinical_limits"
    CLINICAL_FOLLOW_UP = "clinical_follow_up"
    COMMUNICATION = "communication"
    STAFF_OPERATIONS = "staff_operations"

    ACCOUNT_ACCESS = "account_access"
    CONSENT_HISTORY = "consent_history"
    DATA_CONFIRMATION = "data_confirmation"
    DATA_ACCESS = "data_access"
    DATA_CORRECTION = "data_correction"
    DATA_ANONYMIZATION_BLOCKING_OR_ERASURE = "data_anonymization_blocking_or_erasure"
    DATA_PORTABILITY = "data_portability"
    PROCESSING_INFORMATION = "processing_information"
    DATA_SHARING_INFORMATION = "data_sharing_information"
    CONSENT_REVOCATION = "consent_revocation"
    PRIVACY_REQUEST = "privacy_request"
    DATA_EXPORT = "data_export"
    DATA_ERASURE = "data_erasure"
    AUTOMATED_DECISION_REVIEW = "automated_decision_review"
    PETITION_AUTHORITY = "petition_authority"


@dataclass(frozen=True, slots=True)
class PurposeDefinition:
    """Authoritative classification and mandatory flag for one purpose."""

    classification: PurposeClassification
    is_mandatory: bool


_BASIC_RIGHT_DEFINITION = PurposeDefinition(
    classification=PurposeClassification.BASIC_RIGHT,
    is_mandatory=False,
)

PURPOSE_CATALOG: dict[ConsentPurpose, PurposeDefinition] = {
    ConsentPurpose.TERMS_OF_USE: PurposeDefinition(
        PurposeClassification.CONTRACTUAL_REQUIREMENT,
        True,
    ),
    ConsentPurpose.CLINICAL_LIMITS: PurposeDefinition(
        PurposeClassification.CONTRACTUAL_REQUIREMENT,
        True,
    ),
    ConsentPurpose.CLINICAL_FOLLOW_UP: PurposeDefinition(
        PurposeClassification.OPTIONAL_CONSENT,
        False,
    ),
    ConsentPurpose.COMMUNICATION: PurposeDefinition(
        PurposeClassification.OPTIONAL_CONSENT,
        False,
    ),
    ConsentPurpose.STAFF_OPERATIONS: PurposeDefinition(
        PurposeClassification.OPTIONAL_CONSENT,
        False,
    ),
    **{
        purpose: _BASIC_RIGHT_DEFINITION
        for purpose in (
            ConsentPurpose.ACCOUNT_ACCESS,
            ConsentPurpose.CONSENT_HISTORY,
            ConsentPurpose.DATA_CONFIRMATION,
            ConsentPurpose.DATA_ACCESS,
            ConsentPurpose.DATA_CORRECTION,
            ConsentPurpose.DATA_ANONYMIZATION_BLOCKING_OR_ERASURE,
            ConsentPurpose.DATA_PORTABILITY,
            ConsentPurpose.PROCESSING_INFORMATION,
            ConsentPurpose.DATA_SHARING_INFORMATION,
            ConsentPurpose.CONSENT_REVOCATION,
            ConsentPurpose.PRIVACY_REQUEST,
            ConsentPurpose.DATA_EXPORT,
            ConsentPurpose.DATA_ERASURE,
            ConsentPurpose.AUTOMATED_DECISION_REVIEW,
            ConsentPurpose.PETITION_AUTHORITY,
        )
    },
}

_PURPOSE_DOCUMENT_TYPES: dict[ConsentPurpose, str] = {
    ConsentPurpose.TERMS_OF_USE: "terms",
    ConsentPurpose.CLINICAL_LIMITS: "clinical_limits",
    ConsentPurpose.CLINICAL_FOLLOW_UP: "consent",
    ConsentPurpose.COMMUNICATION: "consent",
    ConsentPurpose.STAFF_OPERATIONS: "consent",
}

_PURPOSE_LABELS_PT_BR: dict[ConsentPurpose, str] = {
    ConsentPurpose.TERMS_OF_USE: "Termos de uso",
    ConsentPurpose.CLINICAL_LIMITS: "Limites do atendimento",
    ConsentPurpose.CLINICAL_FOLLOW_UP: "Acompanhamento clínico",
    ConsentPurpose.COMMUNICATION: "Comunicação",
    ConsentPurpose.STAFF_OPERATIONS: "Operação da equipe",
}


def purpose_definition(purpose: ConsentPurpose | str) -> PurposeDefinition:
    """Resolve a purpose through the closed catalog or reject it."""
    return PURPOSE_CATALOG[ConsentPurpose(purpose)]


def document_type_for_purpose(purpose: ConsentPurpose | str) -> str:
    """Return the document type compatible with a consent purpose."""
    return _PURPOSE_DOCUMENT_TYPES[ConsentPurpose(purpose)]


def purpose_label_pt_br(purpose: ConsentPurpose | str) -> str:
    """Return a user-facing label without exposing a persisted enum."""
    return _PURPOSE_LABELS_PT_BR[ConsentPurpose(purpose)]


def basic_right_purposes() -> frozenset[ConsentPurpose]:
    """Return every purpose that consent can never block."""
    return frozenset(
        purpose
        for purpose, definition in PURPOSE_CATALOG.items()
        if definition.classification is PurposeClassification.BASIC_RIGHT
    )


__all__ = [
    "AuthorizationPolicy",
    "PURPOSE_CATALOG",
    "ConsentPurpose",
    "PurposeClassification",
    "PurposeDefinition",
    "basic_right_purposes",
    "document_type_for_purpose",
    "purpose_definition",
    "purpose_label_pt_br",
]
