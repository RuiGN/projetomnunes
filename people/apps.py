"""Django configuration for the people domain."""

from django.apps import AppConfig


class PeopleConfig(AppConfig):
    """Configure the people boundary."""

    name = "people"

    def ready(self) -> None:
        """Register idempotent account lifecycle side effects explicitly."""
        from . import receivers

        del receivers
