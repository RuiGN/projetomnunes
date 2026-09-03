"""Rendering contracts for reusable cards, states, tables, and pagination."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from clinics.models import ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


def _render(template: str, **context: Any) -> str:
    return render_to_string(template, context)


class _MainContentParser(HTMLParser):
    """Collect text rendered inside the operational main landmark only."""

    def __init__(self) -> None:
        super().__init__()
        self._main_depth = 0
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "main":
            self._main_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "main" and self._main_depth:
            self._main_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._main_depth:
            self.text.append(data)


def _main_text(content: str) -> str:
    parser = _MainContentParser()
    parser.feed(content)
    return " ".join(parser.text)


def test_summary_card_renders_semantics_trend_and_action() -> None:
    content = _render(
        "components/summary_card.html",
        card={
            "id": "summary-active",
            "title": "Cadastros ativos",
            "description": "Registros operacionais disponíveis.",
            "value": "12",
            "raw_value": 12,
            "trend_label": "2 novos no período",
            "tone": "info",
            "action": {"label": "Ver cadastros", "url": "/workspace/?view=active"},
        },
    )

    assert '<article class="summary-card tone-info"' in content
    assert 'aria-labelledby="summary-active-title"' in content
    assert '<h2 id="summary-active-title">Cadastros ativos</h2>' in content
    assert '<data value="12">12</data>' in content
    assert 'aria-label="Tendência: 2 novos no período"' in content
    assert 'href="/workspace/?view=active"' in content
    assert ">Ver cadastros<" in content


def test_summary_card_escapes_values_and_allowlists_tone() -> None:
    content = _render(
        "components/summary_card.html",
        card={
            "id": "unsafe-card",
            "title": "<script>alert(1)</script>",
            "description": "<strong>não confiável</strong>",
            "value": "<img src=x onerror=alert(1)>",
            "raw_value": "<12>",
            "trend_label": "<script>trend</script>",
            "tone": "javascript:alert(1)",
            "action": None,
        },
    )

    assert "<script>" not in content
    assert "<img" not in content
    assert "&lt;script&gt;" in content
    assert "&lt;strong&gt;" in content
    assert 'class="summary-card tone-neutral"' in content
    assert "javascript:alert(1)" not in content


@pytest.mark.parametrize(
    ("kind", "title"),
    (
        ("loading", "Carregando conteúdo"),
        ("empty", "Nenhum item cadastrado"),
        ("no_results", "Nenhum resultado encontrado"),
        ("unavailable", "Conteúdo temporariamente indisponível"),
        ("error", "Não foi possível carregar o conteúdo"),
        ("restricted", "Acesso não autorizado"),
    ),
)
def test_content_state_supports_every_allowlisted_kind(kind: str, title: str) -> None:
    content = _render(
        "components/content_state.html",
        state={
            "kind": kind,
            "title": title,
            "message": "Revise as opções disponíveis e tente novamente.",
            "announce": False,
            "action": None,
        },
    )

    assert f'class="content-state state-{kind}"' in content
    assert f"<h2>{title}</h2>" in content
    assert 'aria-hidden="true"' in content
    assert 'aria-live="polite"' not in content
    assert 'role="status"' not in content


def test_content_state_announces_change_and_escapes_action() -> None:
    content = _render(
        "components/content_state.html",
        state={
            "kind": "error",
            "title": "Falha temporária",
            "message": "Tente novamente sem reenviar dados.",
            "announce": True,
            "action": {"label": "Tentar novamente", "url": "/workspace/?retry=1"},
        },
    )

    assert 'role="status"' in content
    assert 'aria-live="polite"' in content
    assert 'href="/workspace/?retry=1"' in content
    assert ">Tentar novamente<" in content


def test_restricted_state_does_not_confirm_protected_resource() -> None:
    content = _render(
        "components/content_state.html",
        state={
            "kind": "restricted",
            "title": "Acesso não autorizado",
            "message": "Você não tem permissão para acessar este conteúdo.",
            "announce": False,
            "action": {"label": "Voltar à área de trabalho", "url": "/workspace/"},
        },
    )

    assert "Você não tem permissão para acessar este conteúdo." in content
    assert "paciente" not in content.casefold()
    assert "registro existe" not in content.casefold()


def test_build_query_url_allowlists_replaces_and_sorts_parameters() -> None:
    from core.presentation import build_query_url

    result = build_query_url(
        {"q": "Horizonte", "order": "name", "token": "secret", "page": "1"},
        overrides={"page": "2"},
        allowed_keys={"q", "order", "page"},
    )

    assert result == "?order=name&page=2&q=Horizonte"
    assert "token" not in result


@pytest.mark.parametrize(
    ("query", "overrides", "expected"),
    (
        ({"q": ""}, {}, ""),
        ({"q": "Clínica Sul"}, {}, "?q=Cl%C3%ADnica+Sul"),
        ({"page": "2"}, {"page": ""}, ""),
        ({"ignored": "value"}, {"ignored": "other"}, ""),
    ),
)
def test_build_query_url_handles_blank_unicode_and_unknown_keys(
    query: dict[str, str], overrides: dict[str, str], expected: str
) -> None:
    from core.presentation import build_query_url

    assert (
        build_query_url(
            query,
            overrides=overrides,
            allowed_keys={"q", "order", "page"},
        )
        == expected
    )


def _table_context() -> dict[str, Any]:
    return {
        "table": {
            "id": "activity-table",
            "caption": "Atividades operacionais recentes",
            "columns": [
                {
                    "key": "name",
                    "label": "Atividade",
                    "order_url": "?order=-name",
                    "aria_sort": "ascending",
                },
                {
                    "key": "status",
                    "label": "Situação",
                    "order_url": "?order=status",
                    "aria_sort": None,
                },
            ],
            "rows": [
                {
                    "id": "activity-1",
                    "cells": ["Configuração inicial", "Concluída"],
                    "actions": [
                        {
                            "label": "Abrir Configuração inicial",
                            "url": "/workspace/?item=1",
                        }
                    ],
                }
            ],
        }
    }


def test_responsive_table_preserves_native_and_mobile_semantics() -> None:
    content = _render("components/responsive_table.html", **_table_context())

    assert '<div class="responsive-table-wrapper">' in content
    assert '<table class="responsive-table">' in content
    assert "<caption>Atividades operacionais recentes</caption>" in content
    assert content.count('scope="col"') == 3
    assert 'aria-sort="ascending"' in content
    assert '<th scope="row">Configuração inicial</th>' in content
    assert '<section class="mobile-row-list"' in content
    assert '<article class="mobile-row-card"' in content
    assert "<dt>Atividade</dt>" in content
    assert "<dd>Configuração inicial</dd>" in content
    assert "aria-hidden" not in content
    assert ">Abrir Configuração inicial<" in content


def test_responsive_table_escapes_cells_and_actions() -> None:
    context = _table_context()
    context["table"]["rows"][0]["cells"][0] = "<script>alert(1)</script>"
    context["table"]["rows"][0]["actions"][0]["label"] = "<b>Abrir</b>"

    content = _render("components/responsive_table.html", **context)

    assert "<script>" not in content
    assert "<b>" not in content
    assert "&lt;script&gt;" in content
    assert "&lt;b&gt;Abrir&lt;/b&gt;" in content


def test_pagination_renders_middle_page_and_boundaries() -> None:
    content = _render(
        "components/pagination.html",
        pagination={
            "current": 2,
            "current_label": "Página 2 de 3",
            "page_count": 3,
            "first": "?page=1",
            "previous": "?page=1",
            "pages": [
                {"number": 1, "url": "?page=1", "current": False},
                {"number": 2, "url": "?page=2", "current": True},
                {"number": 3, "url": "?page=3", "current": False},
            ],
            "next": "?page=3",
            "last": "?page=3",
        },
    )

    assert '<nav class="pagination" aria-label="Paginação">' in content
    assert "Página 2 de 3" in content
    assert 'aria-current="page">2</span>' in content
    assert 'href="?page=1"' in content
    assert 'href="?page=3"' in content
    assert ">Primeira<" in content
    assert ">Última<" in content


def test_pagination_suppresses_unavailable_links_and_single_page() -> None:
    content = _render(
        "components/pagination.html",
        pagination={
            "current": 1,
            "current_label": "Página 1 de 1",
            "page_count": 1,
            "first": None,
            "previous": None,
            "pages": [{"number": 1, "url": "?page=1", "current": True}],
            "next": None,
            "last": None,
        },
    )

    assert "Página 1 de 1" in content
    assert "Primeira" not in content
    assert "Anterior" not in content
    assert "Próxima" not in content
    assert "Última" not in content
    assert 'href="?page=1"' not in content


def _login_component_user(client: Client, *, is_staff: bool = False) -> None:
    user = UserFactory.create(is_staff=is_staff)
    clinic = ClinicFactory.create(name="Clínica Componentes")
    ClinicMembershipFactory.create(
        user=user,
        clinic=clinic,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()


@pytest.mark.django_db
def test_visual_reference_catalogs_all_component_variants(client: Client) -> None:
    _login_component_user(client, is_staff=True)

    response = client.get(reverse("design_system_reference"))
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    for tone in ("neutral", "info", "success", "warning", "danger"):
        assert f"tone-{tone}" in content
    for kind in (
        "loading",
        "empty",
        "no_results",
        "unavailable",
        "error",
        "restricted",
    ):
        assert f"state-{kind}" in content
    assert "Atividades operacionais recentes" in content
    assert "Página 1 de 3" in content
    assert "Fuso horário efetivo" in content
    assert "Identificadores pessoais" in content


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", ("workspace_vertical", "workspace_detached"))
def test_workspace_integrates_components_without_clinical_demo_data(
    client: Client, route_name: str
) -> None:
    _login_component_user(client)

    response = client.get(reverse(route_name))
    content = response.content.decode("utf-8")
    operational_content = _main_text(content).casefold()

    assert response.status_code == 200
    assert "Módulos disponíveis" in content
    assert "Configurações pendentes" in content
    assert "Atividades da plataforma" in content
    assert '<table class="responsive-table">' in content
    assert "paciente" not in operational_content
    assert "diagnóstico" not in operational_content
    assert "john doe" not in operational_content

    filtered = client.get(
        reverse(route_name), {"q": "<script>alert(1)</script>"}
    ).content.decode("utf-8")
    assert "<script>alert(1)</script>" not in filtered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in filtered
    assert "Nenhum resultado encontrado" in filtered


@pytest.mark.django_db
def test_workspace_filter_preserves_the_active_order(client: Client) -> None:
    _login_component_user(client)

    content = client.get(
        reverse("workspace_vertical"), {"order": "-status"}
    ).content.decode("utf-8")

    assert '<input type="hidden" name="order" value="-status">' in content


@pytest.mark.django_db
def test_visual_reference_pagination_matches_the_rendered_table(client: Client) -> None:
    _login_component_user(client, is_staff=True)

    content = client.get(
        reverse("design_system_reference"), {"page": "3"}
    ).content.decode("utf-8")

    assert "Permissões da equipe" in content
    assert "Página 3 de 3" in content
    assert "Página 2 de 3" not in content


def test_component_css_has_accessible_responsive_contracts() -> None:
    css = (Path(settings.BASE_DIR) / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    compact = " ".join(css.split())

    for selector in (
        ".summary-card-grid",
        ".summary-card",
        ".content-state",
        ".responsive-table",
        ".mobile-row-list",
        ".pagination",
    ):
        assert selector in css
    assert "min-height: 44px" in css
    assert "border-radius: 14px" in css
    assert "var(--color-surface)" in css
    assert "var(--color-border)" in css
    assert "var(--color-text-muted)" in css
    assert ".mobile-row-list { display: none; }" in compact
    assert "@media (max-width: 700px)" in css
    assert ".responsive-table-wrapper { display: none; }" in compact
    assert ".mobile-row-list { display: grid; }" in compact
    assert "overflow-x: auto" not in css
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_visual_reference_explains_density_truncation_dates_and_masking() -> None:
    template = (
        Path(settings.BASE_DIR) / "templates" / "visual_reference" / "reference.html"
    ).read_text(encoding="utf-8")

    assert "Fuso horário efetivo" in template
    assert "Identificadores pessoais" in template
    assert "Truncamento" in template
    assert "Ausência de dados" in template
    assert "densidade" in template.casefold()
