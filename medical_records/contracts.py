"""Domain contracts, enums and constants for medical_records."""

from enum import StrEnum
from typing import Final

ALLOWED_DOCUMENT_MIME_TYPES: Final[tuple[str, ...]] = (
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/dicom",
    "text/plain",
)

MAX_DOCUMENT_SIZE_BYTES: Final[int] = 50 * 1024 * 1024  # 50 MB
DEFAULT_CLINICAL_RETENTION_YEARS: Final[int] = 20  # CFM Res 1821/2007
DEFAULT_SIGNED_URL_EXPIRY_SECONDS: Final[int] = 900  # 15 minutes


class EpisodeStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    TRANSFERRED = "transferred"
    ARCHIVED = "archived"


class RecordEntryType(StrEnum):
    CLINICAL_EVOLUTION = "clinical_evolution"
    ASSESSMENT = "assessment"
    CONSULTATION_NOTE = "consultation_note"
    ADMINISTRATIVE_NOTE = "administrative_note"
    DISCHARGE_SUMMARY = "discharge_summary"
    EMERGENCY_NOTE = "emergency_note"


class RecordEntryStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    SIGNED = "signed"
    AMENDED = "amended"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class PurposeOfUse(StrEnum):
    CARE_DELIVERY = "care_delivery"
    ADMINISTRATIVE = "administrative"
    LEGAL_AUDIT = "legal_audit"
    SCIENTIFIC_RESEARCH = "scientific_research"
    EMERGENCY = "emergency"


class DocumentType(StrEnum):
    PRESCRIPTION = "prescription"
    MEDICAL_CERTIFICATE = "medical_certificate"
    MEDICAL_REPORT = "medical_report"
    REFERRAL = "referral"
    EXAM_RESULT = "exam_result"
    ADMINISTRATIVE_FORM = "administrative_form"
    CONSENT_TERM = "consent_term"


class ConfidentialityLevel(StrEnum):
    STANDARD = "standard"
    RESTRICTED = "restricted"
    HIGHLY_CONFIDENTIAL = "highly_confidential"


class DocumentScanStatus(StrEnum):
    QUARANTINE = "quarantine"
    SCANNING = "scanning"
    CLEAN = "clean"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class SignatureLevel(StrEnum):
    SIMPLE = "simple"
    ADVANCED = "advanced"
    QUALIFIED_ICP_BRASIL = "qualified_icp_brasil"


class SignatureType(StrEnum):
    CLINICAL_SIGNOFF = "clinical_signoff"
    PATIENT_ACKNOWLEDGEMENT = "patient_acknowledgement"
    ADMINISTRATIVE_APPROVAL = "administrative_approval"


class SignatureStatus(StrEnum):
    VALID = "valid"
    REVOKED = "revoked"
    EXPIRED = "expired"
    TAMPERED = "tampered"


class SignerRole(StrEnum):
    ATTENDING_PHYSICIAN = "attending_physician"
    THERAPIST = "therapist"
    CLINICAL_DIRECTOR = "clinical_director"
    PATIENT = "patient"
    LEGAL_GUARDIAN = "legal_guardian"


class AddendumReason(StrEnum):
    CORRECTION = "correction"
    SUPPLEMENTAL_INFO = "supplemental_info"
    LATE_ENTRY = "late_entry"
    ADMINISTRATIVE_AMENDMENT = "administrative_amendment"


class LegalBaseRetention(StrEnum):
    CFM_RES_1821_2007 = "cfm_res_1821_2007"
    LGPD_ART_16 = "lgpd_art_16"
    CC_ART_206 = "cc_art_206"
    ADMINISTRATIVE_NORM = "administrative_norm"


class RetentionTrigger(StrEnum):
    CREATION_DATE = "creation_date"
    EPISODE_END_DATE = "episode_end_date"
    PATIENT_MAJORITY_DATE = "patient_majority_date"


class DisposalAction(StrEnum):
    PERMANENT_ARCHIVE = "permanent_archive"
    SECURE_DESTRUCTION = "secure_destruction"
    ANONYMIZATION = "anonymization"


class DisposalBatchStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ExportFormat(StrEnum):
    PDF = "pdf"
    JSON_FHIR = "json_fhir"
    ZIP_AUDIT = "zip_audit"


class ExportStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    EXPIRED = "expired"
    DOWNLOADED = "downloaded"
