"""Privacy domain application configuration."""

from django.apps import AppConfig


class PrivacyConfig(AppConfig):
    """Register data-subject rights and lifecycle capabilities."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "privacy"
