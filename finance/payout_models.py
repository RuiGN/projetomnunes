"""Revenue split rules, payout batches and fiscal document persistence."""

from __future__ import annotations

from decimal import Decimal
from typing import NoReturn
from uuid import UUID

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.persistence import UUIDTimestampedModel


class PayoutRuleQuerySet(models.QuerySet["PayoutRule"]):
    def for_clinic(self, clinic_id: UUID) -> PayoutRuleQuerySet:
        return self.filter(clinic_id=clinic_id)


class PayoutRuleManager(models.Manager["PayoutRule"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("PayoutRule queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> PayoutRuleQuerySet:
        return PayoutRuleQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructurePayoutRuleManager(models.Manager["PayoutRule"]):
    def get_queryset(self) -> PayoutRuleQuerySet:
        return PayoutRuleQuerySet(self.model, using=self._db)


class PayoutRule(UUIDTimestampedModel):
    """One versioned revenue-split rule for a professional or the clinic."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="payout_rules",
    )
    professional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payout_rules",
    )
    service = models.ForeignKey(
        "scheduling.Service",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payout_rules",
    )
    version = models.PositiveIntegerField(default=1)
    percent_rate = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal("0.0")
    )
    fixed_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    retention_rate = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal("0.0")
    )
    valid_from = models.DateField()
    valid_until = models.DateField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    objects = PayoutRuleManager()
    infrastructure_objects = InfrastructurePayoutRuleManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.CheckConstraint(
                condition=Q(percent_rate__gte=0) & Q(percent_rate__lte=1),
                name="payout_rate_between_zero_and_one",
            ),
            models.CheckConstraint(
                condition=Q(fixed_amount__gte=0), name="payout_fixed_non_negative"
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True)
                | Q(valid_until__gte=models.F("valid_from")),
                name="payout_rule_valid_dates",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "professional", "valid_from"), name="payout_rule_idx"
            ),
        ]


class PayoutBatchQuerySet(models.QuerySet["PayoutBatch"]):
    def for_clinic(self, clinic_id: UUID) -> PayoutBatchQuerySet:
        return self.filter(clinic_id=clinic_id)


class PayoutBatchManager(models.Manager["PayoutBatch"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("PayoutBatch queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> PayoutBatchQuerySet:
        return PayoutBatchQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructurePayoutBatchManager(models.Manager["PayoutBatch"]):
    def get_queryset(self) -> PayoutBatchQuerySet:
        return PayoutBatchQuerySet(self.model, using=self._db)


class PayoutBatch(UUIDTimestampedModel):
    """One approved payout batch with item-level calculation memory."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        APPROVED = "approved", "Aprovado"
        SETTLED = "settled", "Liquidado"
        FAILED = "failed", "Falhou"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="payout_batches",
    )
    professional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payout_batches",
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="BRL")
    calculation_memory = models.JSONField(default=list, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payout_batches_approved",
    )
    settled_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=64)

    objects = PayoutBatchManager()
    infrastructure_objects = InfrastructurePayoutBatchManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "idempotency_key"),
                name="unique_payout_batch_idempotency_per_clinic",
            ),
            models.CheckConstraint(
                condition=Q(total_amount__gte=0), name="payout_total_non_negative"
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "professional", "status"), name="payout_batch_idx"
            ),
        ]


class FiscalDocumentQuerySet(models.QuerySet["FiscalDocument"]):
    def for_clinic(self, clinic_id: UUID) -> FiscalDocumentQuerySet:
        return self.filter(clinic_id=clinic_id)


class FiscalDocumentManager(models.Manager["FiscalDocument"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("FiscalDocument queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> FiscalDocumentQuerySet:
        return FiscalDocumentQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureFiscalDocumentManager(models.Manager["FiscalDocument"]):
    def get_queryset(self) -> FiscalDocumentQuerySet:
        return FiscalDocumentQuerySet(self.model, using=self._db)


class FiscalDocument(UUIDTimestampedModel):
    """One invoice or receipt tracked through a normalized provider state."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        ISSUED = "issued", "Emitido"
        CANCELED = "canceled", "Cancelado"
        FAILED = "failed", "Falhou"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="fiscal_documents",
    )
    charge = models.ForeignKey(
        "finance.Charge",
        on_delete=models.PROTECT,
        related_name="fiscal_documents",
    )
    document_type = models.CharField(
        max_length=16,
        choices=(("invoice", "Nota fiscal"), ("receipt", "Recibo")),
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    document_number = models.CharField(max_length=64, blank=True)
    competence_date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="BRL")
    normalized_error = models.CharField(max_length=255, blank=True)
    idempotency_key = models.CharField(max_length=64)

    objects = FiscalDocumentManager()
    infrastructure_objects = InfrastructureFiscalDocumentManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "idempotency_key"),
                name="unique_fiscal_idempotency_per_clinic",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "status", "competence_date"), name="fiscal_status_idx"
            ),
        ]
