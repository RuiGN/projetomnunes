"""Private file storage for message attachments.

Attachments are stored outside the public media root so they are never served
statically; downloads flow only through the authorized, scan-gated view.
"""

from __future__ import annotations

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateAttachmentStorage(FileSystemStorage):
    """Filesystem storage rooted at PRIVATE_MEDIA_ROOT with no public base URL."""

    def __init__(self) -> None:
        super().__init__(
            location=getattr(settings, "PRIVATE_MEDIA_ROOT", None),
            base_url=None,
        )
