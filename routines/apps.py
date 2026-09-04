"""App configuration for the routines domain."""

from django.apps import AppConfig


class RoutinesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "routines"
    verbose_name = "Routines, Habits, Medications and Care Plans"
