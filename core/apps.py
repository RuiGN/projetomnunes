"""Django configuration for shared domain primitives."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configure the dependency-free core boundary."""

    name = "core"
