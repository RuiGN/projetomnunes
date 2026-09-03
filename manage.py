#!/usr/bin/env python
"""Django command-line utility."""

import os
import sys


def main() -> None:
    """Run administrative tasks with development settings by default."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django is unavailable. Install the project dependencies first."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
