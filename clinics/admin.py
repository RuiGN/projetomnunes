"""Infrastructure-only administration for clinic tenant records."""

from typing import Any

from django import forms
from django.contrib import admin
from django.db import models
from django.db.models import QuerySet
from django.http import HttpRequest

from .models import Clinic, ClinicMembership


@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Manage tenant roots through the explicit unrestricted manager."""

    list_display = ("name", "slug", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    readonly_fields = ("id", "created_at", "updated_at")

    def get_queryset(self, request: HttpRequest) -> QuerySet[Clinic]:
        """Use the global manager only inside exempt admin infrastructure."""
        return Clinic.infrastructure_objects.all()

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: Clinic | None = None,
    ) -> tuple[str, ...]:
        """Keep an existing clinic slug stable in administration."""
        fields = tuple(super().get_readonly_fields(request, obj))
        return fields + (("slug",) if obj is not None else ())


@admin.register(ClinicMembership)
class ClinicMembershipAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Manage memberships through the explicit infrastructure manager."""

    list_display = ("user", "clinic", "role", "is_active", "valid_until")
    list_filter = ("is_active", "role")
    search_fields = ("user__username", "clinic__name", "clinic__slug")
    readonly_fields = ("id", "created_at", "updated_at")

    def get_queryset(self, request: HttpRequest) -> QuerySet[ClinicMembership]:
        """Use unrestricted access only in exempt admin infrastructure."""
        return ClinicMembership.infrastructure_objects.select_related("user", "clinic")

    def formfield_for_foreignkey(
        self,
        db_field: models.ForeignKey[Any, Any],
        request: HttpRequest,
        **kwargs: Any,
    ) -> Any:
        """Use unrestricted clinic choices only inside admin infrastructure."""
        if db_field.remote_field.model is Clinic:
            using = kwargs.pop("using", None)
            return models.Field.formfield(
                db_field,
                form_class=forms.ModelChoiceField,
                queryset=Clinic.infrastructure_objects.using(using),
                to_field_name=db_field.remote_field.field_name,
                blank=db_field.blank,
                **kwargs,
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
