"""Run and persist one authorized access-lifecycle review."""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Any, cast
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from consents.services import review_access_lifecycle


def _uuid_option(value: object, *, label: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise CommandError(f"{label} inválido.") from exc


class Command(BaseCommand):
    """Execute a review under the authority of a current clinic administrator."""

    help = "Revisa memberships, papéis, vínculos e consentimentos da clínica."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--clinic-id", required=True)
        parser.add_argument("--actor-id", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        clinic_id = _uuid_option(options["clinic_id"], label="Identificador da clínica")
        actor_id = _uuid_option(options["actor_id"], label="Identificador do ator")
        actor = get_user_model().objects.filter(pk=actor_id).first()
        if actor is None:
            raise CommandError("Ator administrativo não encontrado.")
        try:
            report = review_access_lifecycle(
                clinic_id=clinic_id,
                actor=cast(AbstractBaseUser, actor),
            )
        except (PermissionDenied, ValidationError) as exc:
            raise CommandError(str(exc)) from exc
        noun = "exceção" if len(report.exceptions) == 1 else "exceções"
        self.stdout.write(
            self.style.SUCCESS(
                f"Revisão {report.run_id} registrada com "
                f"{len(report.exceptions)} {noun}."
            )
        )
