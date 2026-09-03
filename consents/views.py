"""HTTP views for reviewing current terms and recording explicit decisions."""

from __future__ import annotations

from typing import TypedDict, cast
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.http import require_GET, require_POST

from clinics.policies import has_active_clinic_role

from .forms import ConsentDecisionForm, ConsentRevocationForm
from .integrity import require_document_integrity
from .models import ConsentDocument, ConsentManifestation, ConsentRevocationWorkItem
from .policies import purpose_label_pt_br
from .selectors import current_documents_for_actor
from .services import (
    acknowledge_revocation_work_item,
    record_consent_manifestation,
    revoke_consent,
)


class ConsentRow(TypedDict):
    """Template row with a stable typed document/form contract."""

    document: ConsentDocument
    form: ConsentDecisionForm
    revocation_form: ConsentRevocationForm
    decision: str | None
    decision_label: str | None
    purpose_label: str


class RevocationWorkRow(TypedDict):
    """Minimized operational references for one revocation work item."""

    work_item: ConsentRevocationWorkItem
    subject_reference: str


def _context(request: HttpRequest) -> tuple[AbstractBaseUser, UUID]:
    actor = request.user
    clinic_id = getattr(getattr(request, "clinic", None), "pk", None)
    if not isinstance(actor, AbstractBaseUser) or not isinstance(clinic_id, UUID):
        raise PermissionDenied
    return actor, clinic_id


def _require_clinic_admin(actor: AbstractBaseUser, clinic_id: UUID) -> None:
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=cast(UUID, actor.pk),
        role="clinic_admin",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied


@login_required
@require_GET
def revocation_work_queue(request: HttpRequest) -> HttpResponse:
    """Expose pending operational revocations only to the active tenant admin."""
    actor, clinic_id = _context(request)
    _require_clinic_admin(actor, clinic_id)
    work_items = list(
        ConsentRevocationWorkItem.objects.for_clinic(clinic_id)
        .filter(status=ConsentRevocationWorkItem.Status.OPEN)
        .select_related(
            "dispatch",
            "dispatch__manifestation",
            "dispatch__manifestation__document",
        )
        .order_by("created_at", "pk")
    )
    rows: list[RevocationWorkRow] = [
        {
            "work_item": work_item,
            "subject_reference": (
                "PAT-"
                + salted_hmac(
                    "consents.revocation-work.subject-reference",
                    f"{clinic_id}:{work_item.dispatch.manifestation.subject_id}",
                    algorithm="sha256",
                )
                .hexdigest()[:12]
                .upper()
            ),
        }
        for work_item in work_items
    ]
    return TemplateResponse(
        request,
        "consents/revocation_work_queue.html",
        {"work_rows": rows},
    )


@login_required
@require_POST
def acknowledge_revocation_work(
    request: HttpRequest, work_item_id: UUID
) -> HttpResponse:
    """Acknowledge one tenant-scoped work item through the public service."""
    actor, clinic_id = _context(request)
    _require_clinic_admin(actor, clinic_id)
    try:
        acknowledge_revocation_work_item(
            clinic_id=clinic_id,
            actor=actor,
            work_item_id=work_item_id,
            acknowledgement_reference=request.POST.get("acknowledgement_reference", ""),
        )
    except ValidationError as exc:
        return TemplateResponse(
            request,
            "consents/revocation_work_error.html",
            {"error": exc},
            status=400,
        )
    return redirect("consent_revocation_work_queue")


@login_required
@require_GET
def consent_center(request: HttpRequest) -> HttpResponse:
    """Display effective mandatory and optional documents separately."""
    actor, clinic_id = _context(request)
    documents = current_documents_for_actor(clinic_id=clinic_id, actor=actor)
    decisions: dict[UUID, str] = {}
    for item in (
        ConsentManifestation.objects.for_clinic(clinic_id)
        .filter(
            subject_id=actor.pk,
            document_id__in=[document.pk for document in documents],
        )
        .order_by("document_id", "-sequence", "-manifested_at")
    ):
        decisions.setdefault(item.document_id, item.decision)
    rows: list[ConsentRow] = [
        {
            "document": document,
            "form": ConsentDecisionForm(),
            "revocation_form": ConsentRevocationForm(),
            "decision": decisions.get(document.pk),
            "decision_label": dict(ConsentManifestation.Decision.choices).get(
                decisions.get(document.pk, "")
            ),
            "purpose_label": purpose_label_pt_br(document.purpose),
        }
        for document in documents
    ]
    return TemplateResponse(
        request,
        "consents/center.html",
        {
            "mandatory_rows": [row for row in rows if row["document"].is_mandatory],
            "optional_rows": [row for row in rows if not row["document"].is_mandatory],
        },
    )


@login_required
@require_POST
def consent_decide(request: HttpRequest, document_id: UUID) -> HttpResponse:
    """Record one self-manifestation without inferring a default decision."""
    actor, clinic_id = _context(request)
    document = (
        ConsentDocument.objects.for_clinic(clinic_id).filter(pk=document_id).first()
    )
    if document is None:
        raise PermissionDenied
    require_document_integrity(document)
    form = ConsentDecisionForm(request.POST)
    if not form.is_valid():
        return TemplateResponse(
            request,
            "consents/decision_error.html",
            {"form": form, "document": document},
            status=400,
        )
    try:
        record_consent_manifestation(
            clinic_id=clinic_id,
            actor=actor,
            subject_id=actor.pk,
            document_id=document.pk,
            decision=form.cleaned_data["decision"],
            request_id=cast(UUID, form.cleaned_data["request_id"]),
            network_origin=request.META.get("REMOTE_ADDR"),
            client_context=request.META.get("HTTP_USER_AGENT"),
        )
    except ValidationError as exc:
        form.add_error(None, exc)
        return TemplateResponse(
            request,
            "consents/decision_error.html",
            {"form": form, "document": document},
            status=409,
        )
    return redirect("consent_center")


@login_required
@require_POST
def consent_revoke(request: HttpRequest, document_id: UUID) -> HttpResponse:
    """Revoke one optional purpose after explicit impact confirmation."""
    actor, clinic_id = _context(request)
    document = (
        ConsentDocument.objects.for_clinic(clinic_id).filter(pk=document_id).first()
    )
    if document is None:
        raise PermissionDenied
    require_document_integrity(document)
    form = ConsentRevocationForm(request.POST)
    if not form.is_valid():
        return TemplateResponse(
            request,
            "consents/revocation_error.html",
            {"form": form, "document": document},
            status=400,
        )
    try:
        revoke_consent(
            clinic_id=clinic_id,
            actor=actor,
            subject_id=actor.pk,
            document_id=document.pk,
            request_id=cast(UUID, form.cleaned_data["request_id"]),
            reason=cast(str, form.cleaned_data["reason"]),
            network_origin=request.META.get("REMOTE_ADDR"),
            client_context=request.META.get("HTTP_USER_AGENT"),
        )
    except ValidationError as exc:
        form.add_error(None, exc)
        return TemplateResponse(
            request,
            "consents/revocation_error.html",
            {"form": form, "document": document},
            status=409,
        )
    return redirect("consent_center")
