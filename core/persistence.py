"""Public persistence primitives shared by concrete domain models."""

from uuid import uuid4

from django.db import models


class UUIDTimestampedModel(models.Model):
    """Abstract UUID identity with timezone-aware Django lifecycle timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
