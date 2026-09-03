"""Report persistence for generated individual and operational reports."""

from __future__ import annotations

from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from django.conf import settings
from django.db import models

from core.persistence import UUIDTimestampedModel

from .storage import PrivateReportStorage


def report_file_upload_to(instance: Report, filename: str) -> str:
    """Build an opaque tenant-owned private path for a generated report."""
    clinic_id = cast(Any, instance).clinic_id
    return f"analytics/{clinic_id}/reports/{uuid4().hex}.txt"


class ReportKind(models.TextChoices):
    INDIVIDUAL = "individual", "Individual"
    OPERATIONAL = "operational", "Operacional"


class ReportStatus(models.TextChoices):
    READY = "ready", "Pronto"
    FAILED = "failed", "Falhou"


class ReportQuerySet(models.QuerySet["Report"]):
    def for_clinic(self, clinic_id: UUID) -> ReportQuerySet:
        return self.filter(clinic_id=clinic_id)


class ReportManager(models.Manager["Report"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Report queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ReportQuerySet:
        return ReportQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureReportManager(models.Manager["Report"]):
    def get_queryset(self) -> ReportQuerySet:
        return ReportQuerySet(self.model, using=self._db)


class Report(UUIDTimestampedModel):
    """One generated report with provenance, formulas and a temporary download."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="reports",
    )
    kind = models.CharField(max_length=16, choices=ReportKind.choices)
    title = models.CharField(max_length=255)
    period_start = models.DateField()
    period_end = models.DateField()
    sources = models.JSONField(default=list, blank=True)
    formulas = models.JSONField(default=list, blank=True)
    limitations = models.TextField(blank=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="generated_reports",
    )
    status = models.CharField(
        max_length=16, choices=ReportStatus.choices, default=ReportStatus.READY
    )
    file = models.FileField(
        upload_to=report_file_upload_to,
        storage=PrivateReportStorage(),
        max_length=255,
        blank=True,
    )
    download_key = models.CharField(max_length=64, unique=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    downloaded_at = models.DateTimeField(null=True, blank=True)
    downloaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="downloaded_reports",
    )

    objects = ReportManager()
    infrastructure_objects = InfrastructureReportManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "kind", "created_at"),
                name="report_clinic_kind_idx",
            ),
        ]
