"""Ad-hoc charges, delinquency, refunds and disputes persistence."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from django.conf import settings
from django.db import models

from core.persistence import UUIDTimestampedModel


class RefundKind(models.TextChoices):
    FULL = "full", "Total"
    PARTIAL = "partial", "Parcial"
    CHARGEBACK = "chargeback", "Disputa"


class RefundStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    APPROVED = "approved", "Aprovado"
    REJECTED = "rejected", "Recusado"


class AdHocChargeQuerySet(models.QuerySet["AdHocCharge"]):
    def for_clinic(self, clinic_id: UUID) -> AdHocChargeQuerySet:
        return self.filter(clinic_id=clinic_id)


class AdHocChargeManager(models.Manager["AdHocCharge"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("AdHocCharge queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> AdHocChargeQuerySet:
        return AdHocChargeQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureAdHocChargeManager(models.Manager["AdHocCharge"]):
    def get_queryset(self) -> AdHocChargeQuerySet:
        return AdHocChargeQuerySet(self.model, using=self._db)


class AdHocCharge(UUIDTimestampedModel):
    """One standalone charge linked to an appointment, not auto-generated."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="ad_hoc_charges",
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.PROTECT,
        related_name="ad_hoc_charges",
    )
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="BRL")
    due_date = models.DateField()
    status = models.CharField(
        max_length=16,
        choices=(
            ("open", "Em aberto"),
            ("paid", "Pago"),
            ("overdue", "Vencido"),
            ("canceled", "Cancelado"),
        ),
        default="open",
    )
    idempotency_key = models.CharField(max_length=64)

    objects = AdHocChargeManager()
    infrastructure_objects = InfrastructureAdHocChargeManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "idempotency_key"),
                name="unique_adhoc_idempotency_per_clinic",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gte=0), name="adhoc_amount_non_negative"
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "status", "due_date"), name="adhoc_status_due_idx"
            ),
        ]


class RefundRequestQuerySet(models.QuerySet["RefundRequest"]):
    def for_clinic(self, clinic_id: UUID) -> RefundRequestQuerySet:
        return self.filter(clinic_id=clinic_id)


class RefundRequestManager(models.Manager["RefundRequest"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("RefundRequest queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> RefundRequestQuerySet:
        return RefundRequestQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureRefundRequestManager(models.Manager["RefundRequest"]):
    def get_queryset(self) -> RefundRequestQuerySet:
        return RefundRequestQuerySet(self.model, using=self._db)


class RefundRequest(UUIDTimestampedModel):
    """One refund, partial refund or chargeback with mandatory justification."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="refund_requests",
    )
    charge = models.ForeignKey(
        "finance.Charge",
        on_delete=models.PROTECT,
        related_name="refunds",
    )
    kind = models.CharField(max_length=16, choices=RefundKind.choices)
    status = models.CharField(
        max_length=16,
        choices=RefundStatus.choices,
        default=RefundStatus.PENDING,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    justification = models.TextField(max_length=1000)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="refund_requests_made",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="refund_requests_decided",
    )
    idempotency_key = models.CharField(max_length=64)

    objects = RefundRequestManager()
    infrastructure_objects = InfrastructureRefundRequestManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "idempotency_key"),
                name="unique_refund_idempotency_per_clinic",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="refund_amount_positive"
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "status", "created_at"), name="refund_status_idx"
            ),
        ]


class ExceptionQueueItemQuerySet(models.QuerySet["ExceptionQueueItem"]):
    def for_clinic(self, clinic_id: UUID) -> ExceptionQueueItemQuerySet:
        return self.filter(clinic_id=clinic_id)


class ExceptionQueueItemManager(models.Manager["ExceptionQueueItem"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("ExceptionQueueItem queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ExceptionQueueItemQuerySet:
        return ExceptionQueueItemQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureExceptionQueueItemManager(models.Manager["ExceptionQueueItem"]):
    def get_queryset(self) -> ExceptionQueueItemQuerySet:
        return ExceptionQueueItemQuerySet(self.model, using=self._db)


class ExceptionQueueItem(UUIDTimestampedModel):
    """One queued finance exception for idempotent reprocessing."""

    class Kind(models.TextChoices):
        ORPHAN_CHARGE = "orphan_charge", "Cobrança órfã"
        AMOUNT_MISMATCH = "amount_mismatch", "Divergência de valor"
        INVALID_WEBHOOK = "invalid_webhook", "Webhook inválido"
        EXPIRED_DISPUTE = "expired_dispute", "Disputa vencida"

    class Status(models.TextChoices):
        OPEN = "open", "Aberto"
        RESOLVED = "resolved", "Resolvido"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="exception_queue_items",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN
    )
    reference = models.CharField(max_length=255, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_exception_items",
    )

    objects = ExceptionQueueItemManager()
    infrastructure_objects = InfrastructureExceptionQueueItemManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "kind", "status"), name="exception_kind_status_idx"
            ),
        ]
