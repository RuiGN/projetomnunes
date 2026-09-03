"""Foundation HTTP views, safe health probes, and error handlers."""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import urlencode
from uuid import uuid4

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Page, Paginator
from django.db import connection
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from accounts.models import User
from accounts.services import rotate_current_session_tracking
from clinics.selectors import active_clinics_for_actor
from clinics.services import UnauthorizedClinicError, switch_active_clinic
from clinics.typing import ClinicRequest
from core.forms import DesignSystemExampleForm
from core.observability import current_request_id
from core.presentation import build_query_url

ACTIVITY_ROWS = (
    ("activity-1", "Configuração inicial", "Concluída"),
    ("activity-2", "Permissões da equipe", "Revisão pendente"),
    ("activity-3", "Identidade visual", "Configurada"),
    ("activity-4", "Canais institucionais", "Disponível"),
    ("activity-5", "Horários de atendimento", "Pendente"),
)
ALLOWED_COMPONENT_QUERY_KEYS = {"q", "order", "page"}


def _pagination_context(
    page: Page[tuple[str, str, str]], query: dict[str, str]
) -> dict[str, object]:
    """Build safe, server-generated pagination destinations."""

    def destination(number: int) -> str:
        return build_query_url(
            query,
            overrides={"page": str(number)},
            allowed_keys=ALLOWED_COMPONENT_QUERY_KEYS,
        )

    return {
        "current": page.number,
        "current_label": f"Página {page.number} de {page.paginator.num_pages}",
        "page_count": page.paginator.num_pages,
        "first": destination(1) if page.has_previous() else None,
        "previous": destination(page.previous_page_number())
        if page.has_previous()
        else None,
        "pages": [
            {
                "number": number,
                "url": destination(number),
                "current": number == page.number,
            }
            for number in page.paginator.page_range
        ],
        "next": destination(page.next_page_number()) if page.has_next() else None,
        "last": destination(page.paginator.num_pages) if page.has_next() else None,
    }


def _component_examples(request: HttpRequest) -> dict[str, object]:
    """Return synthetic, non-clinical primitives for component demonstrations."""
    query: dict[str, str] = {
        key: str(value)
        for key, value in request.GET.items()
        if key in ALLOWED_COMPONENT_QUERY_KEYS
    }
    search_query = query.get("q", "").strip()
    order = query.get("order", "name")
    if order not in {"name", "-name", "status", "-status"}:
        order = "name"
    query["order"] = order

    rows = list(ACTIVITY_ROWS)
    if search_query:
        normalized_query = search_query.casefold()
        rows = [
            row
            for row in rows
            if normalized_query in row[1].casefold()
            or normalized_query in row[2].casefold()
        ]
    field_index = 1 if order.lstrip("-") == "name" else 2
    rows.sort(
        key=lambda row: row[field_index].casefold(), reverse=order.startswith("-")
    )

    page = Paginator(rows, 2).get_page(query.get("page", "1"))
    table_rows = [
        {
            "id": identifier,
            "cells": [name, status],
            "actions": [
                {
                    "label": f"Abrir {name}",
                    "url": build_query_url(
                        query,
                        overrides={"item": identifier},
                        allowed_keys=ALLOWED_COMPONENT_QUERY_KEYS | {"item"},
                    ),
                }
            ],
        }
        for identifier, name, status in page.object_list
    ]
    ordering = {
        "name": ("-name", "ascending"),
        "-name": ("name", "descending"),
        "status": ("-status", "ascending"),
        "-status": ("status", "descending"),
    }
    columns = []
    for key, label in (("name", "Atividade"), ("status", "Situação")):
        next_order = f"-{key}"
        aria_sort = None
        if order.lstrip("-") == key:
            next_order, aria_sort = ordering[order]
        columns.append(
            {
                "key": key,
                "label": label,
                "order_url": build_query_url(
                    query,
                    overrides={"order": next_order, "page": "1"},
                    allowed_keys=ALLOWED_COMPONENT_QUERY_KEYS,
                ),
                "aria_sort": aria_sort,
            }
        )

    summary_cards = [
        {
            "id": "modules-available",
            "title": "Módulos disponíveis",
            "description": "Recursos operacionais liberados para a clínica ativa.",
            "value": "4",
            "raw_value": 4,
            "trend_label": "sem alteração no período",
            "tone": "neutral",
            "action": None,
        },
        {
            "id": "settings-pending",
            "title": "Configurações pendentes",
            "description": "Ajustes factuais que ainda precisam de revisão.",
            "value": "2",
            "raw_value": 2,
            "trend_label": "1 revisão concluída",
            "tone": "warning",
            "action": {"label": "Revisar configurações", "url": "#activity-list"},
        },
        {
            "id": "catalog-info",
            "title": "Informações disponíveis",
            "description": "Exemplo de indicador informativo.",
            "value": "8",
            "raw_value": 8,
            "trend_label": "2 novos registros",
            "tone": "info",
            "action": None,
        },
        {
            "id": "catalog-success",
            "title": "Etapas concluídas",
            "description": "Conclusões confirmadas no fluxo operacional.",
            "value": "6",
            "raw_value": 6,
            "trend_label": "2 conclusões no período",
            "tone": "success",
            "action": None,
        },
        {
            "id": "catalog-danger",
            "title": "Falhas operacionais",
            "description": "Erros técnicos que exigem nova tentativa.",
            "value": "1",
            "raw_value": 1,
            "trend_label": "sem dados sensíveis",
            "tone": "danger",
            "action": None,
        },
    ]
    states = [
        {
            "kind": kind,
            "title": title,
            "message": message,
            "announce": kind == "loading",
            "action": None,
        }
        for kind, title, message in (
            (
                "loading",
                "Carregando conteúdo",
                "Aguarde enquanto os dados autorizados são preparados.",
            ),
            (
                "empty",
                "Nenhum item cadastrado",
                "Cadastre o primeiro item quando estiver pronto.",
            ),
            (
                "no_results",
                "Nenhum resultado encontrado",
                "Revise os filtros aplicados.",
            ),
            (
                "unavailable",
                "Conteúdo temporariamente indisponível",
                "Tente novamente em alguns instantes.",
            ),
            (
                "error",
                "Não foi possível carregar o conteúdo",
                "Tente novamente sem reenviar dados.",
            ),
            (
                "restricted",
                "Acesso não autorizado",
                "Você não tem permissão para acessar este conteúdo.",
            ),
        )
    ]
    return {
        "summary_cards": summary_cards,
        "content_states": states,
        "search_query": search_query,
        "current_order": order,
        "activity_table": {
            "id": "activity-list",
            "caption": "Atividades operacionais recentes",
            "columns": columns,
            "rows": table_rows,
        },
        "activity_pagination": _pagination_context(page, query),
        "reference_form": DesignSystemExampleForm(),
    }


def home(request: HttpRequest) -> HttpResponse:
    """Return a minimal PT-BR availability response."""
    return HttpResponse(
        "Plataforma terapêutica disponível.", content_type="text/plain; charset=utf-8"
    )


def liveness(request: HttpRequest) -> JsonResponse:
    """Report process responsiveness without touching external dependencies."""
    return JsonResponse({"status": "ok"})


def readiness(request: HttpRequest) -> JsonResponse:
    """Check required database and cache dependencies without exposing failures."""
    cache_key = f"readiness:{uuid4().hex}"
    try:
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                raise RuntimeError("Unexpected database readiness response")
        cache.set(cache_key, "ok", timeout=5)
        if cache.get(cache_key) != "ok":
            raise RuntimeError("Unexpected cache readiness response")
        cache.delete(cache_key)
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


@login_required(login_url="/admin/login/")
def design_system_reference(request: HttpRequest) -> TemplateResponse:
    """Render the tenant-scoped visual inventory for authorized staff only."""
    if not cast(User, request.user).is_staff:
        raise PermissionDenied
    reference_form = DesignSystemExampleForm(
        request.POST or None,
        request.FILES or None,
    )
    form_validated = request.method == "POST" and reference_form.is_valid()
    context = _component_examples(request)
    context.update(
        {
            "reference_form": reference_form,
            "reference_form_validated": form_validated,
        }
    )
    return TemplateResponse(
        request,
        "visual_reference/reference.html",
        context,
    )


def _workspace_response(request: HttpRequest, layout_variant: str) -> TemplateResponse:
    """Render one workspace route through the requested reusable shell."""
    return TemplateResponse(
        request,
        "workspace/home.html",
        {
            "layout_template": f"layouts/{layout_variant}.html",
            "layout_variant": layout_variant,
            "page_title": "Área de trabalho",
            **_component_examples(request),
        },
    )


@login_required(login_url="/admin/login/")
def workspace_vertical(request: HttpRequest) -> HttpResponse:
    """Restore the saved layout from the canonical workspace entry point."""
    actor = cast(User, request.user)
    if actor.preferred_layout == User.Layout.DETACHED:
        response = HttpResponse(status=302)
        response.headers["Location"] = reverse("workspace_detached")
        return response
    return _workspace_response(request, "vertical")


@login_required(login_url="/admin/login/")
def workspace_detached(request: HttpRequest) -> TemplateResponse:
    """Render the detached workspace layout with equivalent navigation."""
    return _workspace_response(request, "detached")


@require_POST
@login_required(login_url="/admin/login/")
def save_workspace_layout(request: HttpRequest) -> HttpResponse:
    """Persist an allowlisted workspace layout for the authenticated actor."""
    actor = cast(User, request.user)
    layout = request.POST.get("layout")
    if layout not in User.Layout.values:
        return HttpResponseBadRequest("Preferência de layout inválida.")

    actor.preferred_layout = layout
    actor.save(update_fields=["preferred_layout"])
    destination = (
        reverse("workspace_detached")
        if layout == User.Layout.DETACHED
        else reverse("workspace_vertical")
    )
    response = HttpResponse(status=302)
    response.headers["Location"] = destination
    return response


def _safe_workspace_redirect(request: HttpRequest, candidate: object) -> str:
    """Return an allowed local destination or the default workspace route."""
    if isinstance(candidate, str) and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse("workspace_vertical")


@require_GET
@login_required(login_url="/admin/login/")
def review_clinic_switch(request: HttpRequest) -> TemplateResponse:
    """Review an authorized clinic switch without changing server state."""
    actor = cast(User, request.user)
    raw_clinic_id = request.GET.get("clinic_id")
    target = next(
        (
            clinic
            for clinic in active_clinics_for_actor(actor)
            if str(clinic.pk) == raw_clinic_id
        ),
        None,
    )
    if target is None:
        raise PermissionDenied
    clinic_request = cast(ClinicRequest, request)
    return TemplateResponse(
        request,
        "clinics/confirm_switch.html",
        {
            "current_clinic": clinic_request.clinic,
            "target_clinic": target,
            "next_url": _safe_workspace_redirect(request, request.GET.get("next")),
        },
    )


@require_POST
@login_required(login_url="/admin/login/")
def confirm_clinic_switch(request: HttpRequest) -> HttpResponse:
    """Reauthorize and persist a confirmed clinic selection."""
    try:
        actor = cast(User, request.user)
        switch_active_clinic(
            request,
            actor,
            request.POST.get("clinic_id"),
        )
        rotate_current_session_tracking(request=request, user=actor)
    except UnauthorizedClinicError as exc:
        raise PermissionDenied from exc
    destination = _safe_workspace_redirect(request, request.POST.get("next"))
    response = HttpResponse(status=302)
    response.headers["Location"] = destination
    return response


def admin_login_redirect(request: HttpRequest) -> HttpResponse:
    """Route Django Admin authentication through the protected account entrypoint."""
    response = HttpResponse(status=302)
    response.headers["Location"] = (
        f"{reverse('account_login')}?{urlencode({'next': '/admin/'})}"
    )
    return response


def _error_response(
    request: HttpRequest, *, status: int, title: str, message: str
) -> TemplateResponse:
    request_id = getattr(request, "request_id", current_request_id())
    return TemplateResponse(
        request,
        f"errors/{status}.html",
        {"title": title, "message": message, "request_id": request_id},
        status=status,
    )


def bad_request(request: HttpRequest, exception: Any = None) -> TemplateResponse:
    """Render a safe PT-BR 400 response."""
    return _error_response(
        request,
        status=400,
        title="Solicitação inválida",
        message="Não foi possível processar sua solicitação.",
    )


def permission_denied(request: HttpRequest, exception: Any = None) -> TemplateResponse:
    """Render a safe PT-BR 403 response."""
    return _error_response(
        request,
        status=403,
        title="Acesso não autorizado",
        message="Você não tem permissão para acessar este conteúdo.",
    )


def page_not_found(request: HttpRequest, exception: Any = None) -> TemplateResponse:
    """Render a safe PT-BR 404 response."""
    return _error_response(
        request,
        status=404,
        title="Página não encontrada",
        message="A página solicitada não foi encontrada.",
    )


def server_error(request: HttpRequest, exception: Any = None) -> TemplateResponse:
    """Render a safe PT-BR 500 response."""
    return _error_response(
        request,
        status=500,
        title="Erro inesperado",
        message="Ocorreu um erro inesperado.",
    )
