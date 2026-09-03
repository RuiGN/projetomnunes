"""Django configuration for the content domain."""

from importlib import import_module

from django.apps import AppConfig


class ContentConfig(AppConfig):
    """Configure the content boundary."""

    name = "content"

    def ready(self) -> None:
        import_module("content.receivers")
