"""Public selector interface for the accounts domain."""

from uuid import UUID

from core.selectors import Selector as Selector

from .models import User


def identity_export_records(
    *, clinic_id: UUID, subject_id: UUID
) -> list[dict[str, object]]:
    """Return subject-owned fields only when related to the explicit clinic."""
    identity = (
        User.objects.filter(
            pk=subject_id,
            clinic_memberships__clinic_id=clinic_id,
        )
        .values(
            "id",
            "email",
            "first_name",
            "last_name",
            "is_active",
            "date_joined",
            "last_login",
        )
        .first()
    )
    if identity is None:
        return []
    return [
        {
            "type": "account",
            "id": str(identity["id"]),
            "email": identity["email"],
            "first_name": identity["first_name"],
            "last_name": identity["last_name"],
            "is_active": identity["is_active"],
            "date_joined": identity["date_joined"].isoformat(),
            "last_login": (
                identity["last_login"].isoformat()
                if identity["last_login"] is not None
                else None
            ),
        }
    ]


__all__ = ["Selector", "identity_export_records"]
