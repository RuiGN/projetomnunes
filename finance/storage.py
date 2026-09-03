"""Private file storage for finance exports and reports."""

from __future__ import annotations

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateFinanceStorage(FileSystemStorage):
    """Filesystem storage rooted at PRIVATE_MEDIA_ROOT with no public base URL."""

    def __init__(self) -> None:
        super().__init__(
            location=getattr(settings, "PRIVATE_MEDIA_ROOT", None),
            base_url=None,
        )
