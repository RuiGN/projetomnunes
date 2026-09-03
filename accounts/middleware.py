"""Session lifetime and privileged multifactor enforcement."""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from clinics.selectors import actor_has_active_role

from .models import User, UserMFA
from .services import register_current_session, validate_current_session

_EXEMPT_PATHS = (
    "/accounts/login/",
    "/accounts/logout/",
    "/accounts/mfa/enroll/",
    "/accounts/mfa/verify/",
)
_EXEMPT_PREFIXES = (
    "/accounts/password-",
    "/static/",
    "/health/",
)


class AccountSecurityMiddleware:
    """Enforce revocation, expiration, and MFA before privileged navigation."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        actor = request.user if isinstance(request.user, User) else None
        if actor is None or not actor.is_authenticated:
            return self.get_response(request)
        if not validate_current_session(request=request, user=actor):
            logout(request)
            return redirect("account_login")
        account_session = register_current_session(request=request, user=actor)
        request.account_session = account_session  # type: ignore[attr-defined]
        if request.path in _EXEMPT_PATHS or request.path.startswith(_EXEMPT_PREFIXES):
            return self.get_response(request)
        if not settings.MFA_ENFORCEMENT_ENABLED:
            return self.get_response(request)
        privileged = (
            actor.is_staff
            or actor.is_superuser
            or actor_has_active_role(actor, role="clinic_admin")
            or actor_has_active_role(actor, role="therapist")
            or actor_has_active_role(actor, role="administrative_staff")
        )
        if not privileged:
            return self.get_response(request)
        mfa = UserMFA.objects.filter(user=actor, is_confirmed=True).first()
        if mfa is None:
            request.session["mfa_next"] = request.get_full_path()
            return redirect("mfa_enroll")
        if not request.session.get("mfa_verified", False):
            request.session["mfa_next"] = request.get_full_path()
            return redirect("mfa_verify")
        return self.get_response(request)
