"""Application-owned security response headers."""

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse


class SecurityHeadersMiddleware:
    """Apply restrictive browser policies to every application response."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response["Content-Security-Policy"] = settings.CONTENT_SECURITY_POLICY
        response["Referrer-Policy"] = settings.REFERRER_POLICY
        response["Permissions-Policy"] = settings.PERMISSIONS_POLICY
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        return response
