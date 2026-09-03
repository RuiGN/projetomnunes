"""Django configuration for the journal domain."""

from django.apps import AppConfig


class JournalConfig(AppConfig):
    """Configure the journal boundary."""

    name = "journal"

    def ready(self) -> None:
        """Ensure audit side effects are loaded for check-in domain events."""
        # Audit receivers are connected by the audit app config; importing the
        # module here is unnecessary. Kept for explicit boundary intent.
        return None
