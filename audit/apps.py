"""Django configuration for the audit domain."""

from importlib import import_module

from django.apps import AppConfig


class AuditConfig(AppConfig):
    """Configure the audit boundary."""

    name = "audit"

    def ready(self) -> None:
        """Register audit receivers after the application registry is ready."""
        import_module("audit.receivers")
