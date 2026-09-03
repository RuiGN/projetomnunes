"""Resolve and attach a clinic tenant to authenticated HTTP requests."""

from collections.abc import Callable
from typing import cast

from django.http import HttpRequest, HttpResponse, JsonResponse

from core.services import update_observability_context

from .services import (
    InvalidClinicSelectionError,
    MissingClinicSelectionError,
    UnauthorizedClinicError,
    resolve_request_clinic,
)
from .typing import ClinicRequest

# Django admin is global infrastructure and overrides tenant-safe model managers.
TENANT_EXEMPT_PATH_PREFIXES = ("/accounts/", "/admin/", "/health/")


def is_tenant_exempt_path(path: str) -> bool:
    """Return whether a path is narrowly exempt infrastructure."""
    return any(path.startswith(prefix) for prefix in TENANT_EXEMPT_PATH_PREFIXES)


class ClinicTenantMiddleware:
    """Authorize one request-local clinic context without global tenant state."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Attach a clinic or safely stop an invalid authenticated request."""
        clinic_request = cast(ClinicRequest, request)
        clinic_request.clinic = None

        if request.user.is_authenticated:
            update_observability_context(actor_id=str(request.user.pk))

        if is_tenant_exempt_path(request.path) or not request.user.is_authenticated:
            return self.get_response(request)

        try:
            clinic_request.clinic = resolve_request_clinic(request, request.user)
            update_observability_context(tenant_id=str(clinic_request.clinic.pk))
        except MissingClinicSelectionError:
            return JsonResponse(
                {"detail": "Selecione uma clínica para continuar."}, status=400
            )
        except InvalidClinicSelectionError:
            return JsonResponse(
                {"detail": "Identificador de clínica inválido."}, status=400
            )
        except UnauthorizedClinicError:
            return JsonResponse(
                {"detail": "Acesso à clínica não autorizado."}, status=403
            )

        return self.get_response(request)
