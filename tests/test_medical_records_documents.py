"""Tests for document quarantine, scanning, upload validation and access (PRD 8.18)."""

from typing import Any

import pytest

from clinics.models import Clinic, ClinicMembership
from medical_records.contracts import DocumentScanStatus, DocumentType
from medical_records.document_models import DocumentAccessLog
from medical_records.document_services import (
    complete_document_scan,
    upload_document_to_quarantine,
)
from medical_records.selectors import get_document_download_url
from people.models import PatientProfile
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Documentos")


@pytest.fixture
def therapist_user(clinic: Clinic) -> Any:
    user = UserFactory.create(email="terapeuta_doc@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def patient_profile(db: Any, clinic: Clinic, therapist_user: Any) -> PatientProfile:
    return PatientProfile.infrastructure_objects.create(
        clinic=clinic,
        user=therapist_user,
        full_name="Paciente Documentos",
        birth_date="1995-05-20",
    )


def test_upload_valid_pdf_enters_quarantine(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    content = b"%PDF-1.4 synthetic clinical document content"
    doc = upload_document_to_quarantine(
        clinic_id=clinic.id,
        patient_id=patient_profile.id,
        uploader_user=therapist_user,
        file_name="laudo.pdf",
        mime_type="application/pdf",
        file_size_bytes=len(content),
        content=content,
        document_type=DocumentType.MEDICAL_REPORT.value,
        title="Laudo Clínico",
    )
    assert doc.scan_status == DocumentScanStatus.QUARANTINE.value
    assert doc.sha256_checksum != ""
    assert doc.clinic_id == clinic.id
    assert doc.patient_id == patient_profile.id


def test_upload_rejected_for_forbidden_mime_type(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    with pytest.raises(ValueError, match="not permitted"):
        upload_document_to_quarantine(
            clinic_id=clinic.id,
            patient_id=patient_profile.id,
            uploader_user=therapist_user,
            file_name="malicious.html",
            mime_type="text/html",
            file_size_bytes=100,
            content=b"<html><script>evil()</script></html>",
        )


def test_upload_rejected_for_unsupported_mime_type(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    content = b"some archive data"
    with pytest.raises(ValueError, match="Unsupported MIME type"):
        upload_document_to_quarantine(
            clinic_id=clinic.id,
            patient_id=patient_profile.id,
            uploader_user=therapist_user,
            file_name="arquivo.zip",
            mime_type="application/zip",
            file_size_bytes=len(content),
            content=content,
        )


def test_upload_rejected_for_embedded_active_content(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    # Polyglot: PDF with embedded script header
    content = b"<script>alert(1)</script>" + b"%PDF-1.4 data"
    with pytest.raises(ValueError, match="forbidden embedded active content"):
        upload_document_to_quarantine(
            clinic_id=clinic.id,
            patient_id=patient_profile.id,
            uploader_user=therapist_user,
            file_name="polyglot.pdf",
            mime_type="application/pdf",
            file_size_bytes=len(content),
            content=content,
        )


def test_clean_document_promoted_after_scan(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    content = b"%PDF-1.4 safe clinical report"
    doc = upload_document_to_quarantine(
        clinic_id=clinic.id,
        patient_id=patient_profile.id,
        uploader_user=therapist_user,
        file_name="safe_report.pdf",
        mime_type="application/pdf",
        file_size_bytes=len(content),
        content=content,
    )
    promoted = complete_document_scan(
        document=doc,
        scan_clean=True,
        promoted_by_user=therapist_user,
    )
    assert promoted.scan_status == DocumentScanStatus.CLEAN.value
    assert promoted.scan_clean is True
    assert promoted.approved_at is not None


def test_infected_document_rejected_after_scan(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    content = b"%PDF-1.4 infected content"
    doc = upload_document_to_quarantine(
        clinic_id=clinic.id,
        patient_id=patient_profile.id,
        uploader_user=therapist_user,
        file_name="infected.pdf",
        mime_type="application/pdf",
        file_size_bytes=len(content),
        content=content,
    )
    rejected = complete_document_scan(
        document=doc,
        scan_clean=False,
        scan_notes="Trojan.Generic detected",
    )
    assert rejected.scan_status == DocumentScanStatus.REJECTED.value
    assert rejected.scan_clean is False
    assert "Trojan" in rejected.quarantine_reason


def test_download_url_generated_with_access_log(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    content = b"%PDF-1.4 report for download"
    doc = upload_document_to_quarantine(
        clinic_id=clinic.id,
        patient_id=patient_profile.id,
        uploader_user=therapist_user,
        file_name="report_dl.pdf",
        mime_type="application/pdf",
        file_size_bytes=len(content),
        content=content,
    )
    # Promote to clean first
    complete_document_scan(
        document=doc, scan_clean=True, promoted_by_user=therapist_user
    )

    url = get_document_download_url(
        clinic_id=clinic.id,
        document_id=doc.id,
        accessor=therapist_user,
        purpose="care_delivery",
    )
    assert "download" in url
    assert str(clinic.id) in url

    # Access log created
    log = DocumentAccessLog.infrastructure_objects.filter(
        document=doc, accessor=therapist_user
    ).first()
    assert log is not None
    assert log.action == "download"


def test_quarantined_document_not_accessible_for_download(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    content = b"%PDF-1.4 still in quarantine"
    doc = upload_document_to_quarantine(
        clinic_id=clinic.id,
        patient_id=patient_profile.id,
        uploader_user=therapist_user,
        file_name="quarantined.pdf",
        mime_type="application/pdf",
        file_size_bytes=len(content),
        content=content,
    )
    with pytest.raises(ValueError, match="not found or not yet cleared"):
        get_document_download_url(
            clinic_id=clinic.id,
            document_id=doc.id,
            accessor=therapist_user,
        )
