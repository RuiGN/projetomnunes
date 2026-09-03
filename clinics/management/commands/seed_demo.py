"""Create reserved, synthetic development demonstration records."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from clinics.models import Clinic, ClinicMembership

DEMO_CLINIC_SLUG = "clinica-demonstracao"
DEMO_CLINIC_NAME = "Clínica Demonstração"
DEMO_USERS = (
    (
        "admin-demo",
        "admin.demo@example.test",
        "Administradora",
        ClinicMembership.Role.CLINIC_ADMIN,
    ),
    (
        "terapeuta-demo",
        "terapeuta.demo@example.test",
        "Terapeuta",
        ClinicMembership.Role.THERAPIST,
    ),
    (
        "paciente-demo",
        "paciente.demo@example.test",
        "Paciente",
        ClinicMembership.Role.PATIENT,
    ),
)


def _require_safe_development_environment() -> None:
    """Fail closed unless every independent local-development gate is enabled."""
    if os.environ.get("DJANGO_ENV", "").casefold() != "development":
        raise CommandError(
            "O seed de demonstração só é permitido em ambiente de desenvolvimento."
        )
    if not settings.DEBUG or not getattr(settings, "ALLOW_DEMO_SEED", False):
        raise CommandError(
            "O seed de demonstração não está habilitado com configuração local segura."
        )


class Command(BaseCommand):
    """Seed the current schema with reserved synthetic demonstration identities."""

    help = "Cria dados sintéticos somente com opt-in local de desenvolvimento."

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        """Converge on one demo clinic and three role memberships."""
        _require_safe_development_environment()
        user_model = get_user_model()
        expected_usernames = [item[0] for item in DEMO_USERS]
        expected_emails = [item[1] for item in DEMO_USERS]
        reserved_users = list(
            user_model.objects.filter(
                Q(username__in=expected_usernames) | Q(email__in=expected_emails)
            )
        )
        clinic = Clinic.infrastructure_objects.filter(slug=DEMO_CLINIC_SLUG).first()
        if clinic is not None and (
            clinic.name != DEMO_CLINIC_NAME or not clinic.is_demo
        ):
            raise CommandError(
                "O slug reservado já pertence a uma clínica que não é de demonstração."
            )

        existing_demo = clinic is not None
        for username, email, first_name, role in DEMO_USERS:
            collisions = [
                user
                for user in reserved_users
                if user.username == username or user.email == email
            ]
            if not collisions:
                if existing_demo:
                    raise CommandError(
                        f"A identidade reservada {username} está incompleta."
                    )
                continue
            if len(collisions) != 1:
                raise CommandError(
                    f"A identidade reservada {username} colide com outro cadastro."
                )
            user = collisions[0]
            identity_matches = (
                user.username == username
                and user.email == email
                and user.first_name == first_name
                and user.last_name == "Demonstração"
            )
            if not existing_demo or not identity_matches or user.has_usable_password():
                raise CommandError(
                    f"O usuário reservado {username} já pertence a outro cadastro."
                )
            membership = ClinicMembership.infrastructure_objects.filter(
                user=user,
                clinic=clinic,
            ).first()
            if membership is None or (
                membership.role != role
                or not membership.is_active
                or membership.valid_from != date(2020, 1, 1)
                or membership.valid_until is not None
            ):
                raise CommandError(
                    f"O vínculo reservado de {username} não corresponde ao seed."
                )

        if not existing_demo:
            clinic = Clinic.infrastructure_objects.create(
                slug=DEMO_CLINIC_SLUG,
                name=DEMO_CLINIC_NAME,
                is_demo=True,
            )
            for username, email, first_name, role in DEMO_USERS:
                user = user_model.objects.create(
                    username=username,
                    email=email,
                    first_name=first_name,
                    last_name="Demonstração",
                )
                user.set_unusable_password()
                user.save(update_fields=("password",))
                ClinicMembership.infrastructure_objects.create(
                    user=user,
                    clinic=clinic,
                    role=role,
                    is_active=True,
                    valid_from=date(2020, 1, 1),
                    valid_until=None,
                )

        self.stdout.write(
            self.style.SUCCESS("Dados sintéticos de demonstração prontos.")
        )
