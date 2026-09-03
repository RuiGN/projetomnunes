"""Process durable consent-revocation delivery obligations."""

from __future__ import annotations

from argparse import ArgumentParser
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from consents.models import ConsentRevocationDispatch
from consents.services import process_revocation_dispatch


class Command(BaseCommand):
    """Retry pending/failed obligations and fail visibly when any remain failed."""

    help = "Processa despachos pendentes ou falhos de revogação de consentimento."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--clinic-id", required=True)
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument(
            "--include-failed",
            action="store_true",
            help="Mantido por compatibilidade; falhas são retentadas por padrão.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            clinic_id = UUID(str(options["clinic_id"]))
        except (TypeError, ValueError, AttributeError) as exc:
            raise CommandError("Identificador de clínica inválido.") from exc
        limit = int(options["limit"])
        if limit < 1:
            raise CommandError("O limite deve ser maior que zero.")
        statuses = Q(
            status__in=(
                ConsentRevocationDispatch.Status.PENDING,
                ConsentRevocationDispatch.Status.FAILED,
            )
        )
        dispatch_ids = list(
            ConsentRevocationDispatch.objects.for_clinic(clinic_id)
            .filter(statuses)
            .order_by("created_at", "id")
            .values_list("id", flat=True)[:limit]
        )
        confirmed = 0
        failed = 0
        for dispatch_id in dispatch_ids:
            result = process_revocation_dispatch(
                clinic_id=clinic_id,
                dispatch_id=dispatch_id,
            )
            if result.status == ConsentRevocationDispatch.Status.CONFIRMED:
                confirmed += 1
            else:
                failed += 1
        overdue_seconds = int(
            getattr(settings, "CONSENT_REVOCATION_OVERDUE_SECONDS", 3600)
        )
        cutoff = timezone.now() - timedelta(seconds=max(overdue_seconds, 0))
        overdue = (
            ConsentRevocationDispatch.objects.for_clinic(clinic_id)
            .filter(statuses, created_at__lte=cutoff)
            .count()
        )
        remaining_failed = (
            ConsentRevocationDispatch.objects.for_clinic(clinic_id)
            .filter(status=ConsentRevocationDispatch.Status.FAILED)
            .count()
        )
        self.stdout.write(f"Confirmados: {confirmed}")
        self.stdout.write(f"Falhos: {failed}")
        self.stdout.write(f"Falhas remanescentes: {remaining_failed}")
        self.stdout.write(f"Obrigações vencidas: {overdue}")
        if remaining_failed or overdue:
            raise CommandError(
                f"Há {remaining_failed} despacho(s) falho(s) e "
                f"{overdue} obrigação(ões) vencida(s)."
            )
