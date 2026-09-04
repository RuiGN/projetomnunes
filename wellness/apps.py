"""App configuration for the wellness domain."""

from django.apps import AppConfig


class WellnessConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wellness"
    verbose_name = "Wellness, Activity, Sobriety and Crisis Mode"
