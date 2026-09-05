"""HTTP acceptance tests for the editorial content and curation domains."""

from __future__ import annotations

import re
from datetime import UTC, date, timedelta
from uuid import uuid4

import pytest
from django.apps import apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.test.utils import override_settings
from django.urls import NoReverseMatch, reverse

import content.models as content_models
import content.services as content_services
from accounts.models import User
from clinics.models import Clinic, ClinicConfiguration, ClinicMembership
from people.models import PatientProfile, ProfessionalCredential, ProfessionalProfile
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _credential_for(clinic: Clinic, user: User, role: str) -> None:
    if role == "clinic_admin":
        member_role = ClinicMembership.Role.CLINIC_ADMIN
    else:
        member_role = ClinicMembership.Role.THERAPIST
    ClinicMembershipFactory.create(clinic=clinic, user=user, role=member_role)
    profile = ProfessionalProfile.infrastructure_objects.create(
        clinic=clinic,
        user=user,
        full_name=f"Professional {user.pk}",
        professional_email=user.email,
        category="psychologist",
    )
    credential = ProfessionalCredential.objects.create(profile=profile)
    credential.status = ProfessionalCredential.Status.VERIFIED
    credential.council_name = "CRP"
    credential.council_number = "123456"
    credential.council_jurisdiction = "PE"
    credential.save()


def _patient(clinic: Clinic, email: str) -> User:
    user = UserFactory.create(email=email)
    ClinicMembershipFactory.create(
        clinic=clinic, user=user, role=ClinicMembership.Role.PATIENT
    )
    PatientProfile.infrastructure_objects.create(
        clinic=clinic,
        user=user,
        full_name=f"Paciente {email}",
        birth_date=date(1990, 1, 1),
        email=email,
    )
    return user


def _clinic_team(clinic: Clinic) -> tuple[User, User, User]:
    admin = UserFactory.create()
    reviewer = UserFactory.create()
    publisher = UserFactory.create()
    for member in (admin, reviewer, publisher):
        _credential_for(clinic, member, "clinic_admin")
    return admin, reviewer, publisher


def _publish_article(
    clinic: Clinic,
    submitter: User,
    reviewer: User,
    publisher: User,
    *,
    slug: str,
    title: str,
    body: str,
) -> content_models.Content:
    content = content_services.start_content(
        clinic_id=clinic.pk,
        actor=submitter,
        slug=slug,
        title=title,
        kind=content_models.ContentKind.ARTICLE,
        body=body,
        request_id=uuid4(),
    )
    content_services.submit_for_review(
        clinic_id=clinic.pk,
        actor=submitter,
        content_id=content.pk,
        request_id=uuid4(),
    )
    content_services.approve_content_version(
        clinic_id=clinic.pk,
        actor=reviewer,
        content_id=content.pk,
        opinion="Parecer favorável.",
        review_valid_days=30,
        request_id=uuid4(),
    )
    return content_services.publish_content_version(
        clinic_id=clinic.pk,
        actor=publisher,
        content_id=content.pk,
        request_id=uuid4(),
    )


def _force_clinic_client(client: Client, clinic: Clinic, user: User) -> None:
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()


def _editorial_url(name: str, **kwargs: object) -> str:
    try:
        return reverse(name, kwargs=kwargs or None)
    except NoReverseMatch:
        pytest.fail(f"Missing editorial route: {name}")


def test_library_lists_published_content(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, reviewer, publisher = _clinic_team(clinic)
    patient = _patient(clinic, "paciente@example.test")
    _publish_article(
        clinic,
        admin,
        reviewer,
        publisher,
        slug="respirar-4-7-8",
        title="Respiração 4-7-8",
        body="Técnica de respiração para acalmar.",
    )
    _force_clinic_client(client, clinic, patient)

    response = client.get(reverse("content_library"))

    assert response.status_code == 200
    assert "Respiração 4-7-8" in response.content.decode()


def test_detail_renders_published_body(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, reviewer, publisher = _clinic_team(clinic)
    patient = _patient(clinic, "paciente@example.test")
    _publish_article(
        clinic,
        admin,
        reviewer,
        publisher,
        slug="autocompaixao",
        title="Autocompaixão",
        body="Pratique bondade consigo mesmo.",
    )
    _force_clinic_client(client, clinic, patient)

    response = client.get(reverse("content_detail", kwargs={"slug": "autocompaixao"}))

    assert response.status_code == 200
    assert "Autocompaixão" in response.content.decode()


def test_detail_404_for_unpublished_content(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, reviewer, publisher = _clinic_team(clinic)
    patient = _patient(clinic, "paciente@example.test")
    content_services.start_content(
        clinic_id=clinic.pk,
        actor=admin,
        slug="rascunho",
        title="Rascunho interno",
        kind=content_models.ContentKind.ARTICLE,
        body="Ainda não publicado.",
        request_id=uuid4(),
    )
    _force_clinic_client(client, clinic, patient)

    response = client.get(reverse("content_detail", kwargs={"slug": "rascunho"}))

    assert response.status_code == 404


def test_library_is_tenant_scoped(client: Client) -> None:
    clinic_a = ClinicFactory.create()
    clinic_b = ClinicFactory.create()
    admin_b, reviewer_b, publisher_b = _clinic_team(clinic_b)
    patient_a = _patient(clinic_a, "paciente-a@example.test")
    _publish_article(
        clinic_b,
        admin_b,
        reviewer_b,
        publisher_b,
        slug="somente-clinica-b",
        title="Material exclusivo da clínica B",
        body="Não deve vazar para a clínica A.",
    )
    _force_clinic_client(client, clinic_a, patient_a)

    library = client.get(reverse("content_library"))
    detail = client.get(reverse("content_detail", kwargs={"slug": "somente-clinica-b"}))

    assert "Material exclusivo da clínica B" not in library.content.decode()
    assert detail.status_code == 404


def test_recommendation_list_scoped_to_recipient(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, reviewer, publisher = _clinic_team(clinic)
    therapist = UserFactory.create()
    _credential_for(clinic, therapist, "therapist")
    patient = _patient(clinic, "paciente@example.test")
    other = _patient(clinic, "outro@example.test")
    content = _publish_article(
        clinic,
        admin,
        reviewer,
        publisher,
        slug="valores-pessoais",
        title="Valores pessoais",
        body="Reflita sobre o que importa.",
    )
    content_services.recommend_content(
        clinic_id=clinic.pk,
        actor=therapist,
        content_id=content.pk,
        patient_id=patient.pk,
        cohort_id=None,
        objective="Trabalhar valores entre sessões",
        priority="normal",
        context="Complemento do plano de cuidado.",
        request_id=uuid4(),
    )

    _force_clinic_client(client, clinic, other)
    response = client.get(reverse("content_recommendations"))

    assert response.status_code == 200
    assert "Trabalhar valores" not in response.content.decode()


def test_publish_action_denied_for_non_admin(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, reviewer, publisher = _clinic_team(clinic)
    therapist = UserFactory.create()
    _credential_for(clinic, therapist, "therapist")
    content = _publish_article(
        clinic,
        admin,
        reviewer,
        publisher,
        slug="ja-publicado",
        title="Já publicado",
        body="Conteúdo publicado.",
    )
    _force_clinic_client(client, clinic, therapist)

    response = client.post(
        reverse("content_publish", kwargs={"content_id": content.pk})
    )

    assert response.status_code == 302


@override_settings(PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND=("/bin/true",))
def test_editorial_http_surface_supports_complete_versioned_workflow(
    client: Client,
) -> None:
    clinic = ClinicFactory.create()
    author, reviewer, publisher = _clinic_team(clinic)
    _force_clinic_client(client, clinic, author)

    dashboard = client.get(_editorial_url("content_editorial_index"))
    create_page = client.get(_editorial_url("content_editorial_create"))
    assert dashboard.status_code == create_page.status_code == 200
    assert "Gestão editorial" in dashboard.content.decode()
    assert "Conteúdo em blocos" in create_page.content.decode()

    created = client.post(
        _editorial_url("content_editorial_create"),
        {
            "slug": "respiracao-editorial",
            "title": "Respiração editorial",
            "kind": content_models.ContentKind.ARTICLE,
            "body": '<p onclick="evil()">Versão um</p><script>alert(1)</script>',
            "language_code": "pt-BR",
            "audience": "patient",
            "categories": "Autocuidado",
            "tags": "respiração, calma",
        },
    )
    assert created.status_code == 302
    content = content_models.Content.objects.for_clinic(clinic.pk).get(
        slug="respiracao-editorial"
    )

    editor = client.get(
        _editorial_url("content_editorial_detail", content_id=content.pk)
    )
    editor_html = editor.content.decode()
    assert editor.status_code == 200
    assert '<label for="id_body">Conteúdo em blocos</label>' in editor_html
    assert 'aria-describedby="editor-help"' in editor_html

    preview = client.get(
        _editorial_url("content_editorial_preview", content_id=content.pk, version=1)
    )
    preview_html = preview.content.decode()
    assert preview.status_code == 200
    assert "Versão um" in preview_html
    assert "<script>alert(1)</script>" not in preview_html
    assert 'onclick="evil()"' not in preview_html
    assert 'class="product-page editorial-preview"' in preview_html
    assert 'class="product-table-card content-body"' in preview_html

    comment_one = client.post(
        _editorial_url("content_editorial_comment", content_id=content.pk, version=1),
        {"body": "Revisar a fonte principal."},
    )
    comment_two = client.post(
        _editorial_url("content_editorial_comment", content_id=content.pk, version=1),
        {"body": "Confirmar linguagem acessível."},
    )
    assert comment_one.status_code == comment_two.status_code == 302
    try:
        comment_model = apps.get_model("content", "ContentVersionComment")
    except LookupError:
        pytest.fail("Missing append-only editorial comment model")
    comments = list(
        comment_model.objects.for_clinic(clinic.pk)
        .filter(content_version__content_id=content.pk)
        .values_list("body", flat=True)
    )
    assert comments == [
        "Revisar a fonte principal.",
        "Confirmar linguagem acessível.",
    ]
    persisted_comment = comment_model.objects.for_clinic(clinic.pk).first()
    persisted_comment.body = "Tentativa de edição."
    with pytest.raises(RuntimeError, match="append-only"):
        persisted_comment.save()
    with pytest.raises(RuntimeError, match="append-only"):
        comment_model.objects.for_clinic(clinic.pk).delete()

    assert (
        client.post(
            _editorial_url("content_editorial_submit", content_id=content.pk)
        ).status_code
        == 302
    )
    _force_clinic_client(client, clinic, reviewer)
    assert (
        client.post(
            _editorial_url("content_editorial_approve", content_id=content.pk),
            {"opinion": "Parecer favorável.", "review_valid_days": "30"},
        ).status_code
        == 302
    )
    _force_clinic_client(client, clinic, publisher)
    assert (
        client.post(
            _editorial_url("content_publish", content_id=content.pk)
        ).status_code
        == 302
    )

    _force_clinic_client(client, clinic, author)
    assert (
        client.post(
            _editorial_url("content_editorial_version", content_id=content.pk),
            {"body": "<h2>Versão dois</h2><p>Texto atualizado.</p>"},
        ).status_code
        == 302
    )
    comparison = client.get(
        _editorial_url("content_editorial_compare", content_id=content.pk),
        {"from": "1", "to": "2"},
    )
    comparison_html = comparison.content.decode()
    assert comparison.status_code == 200
    assert "Versão um" in comparison_html
    assert "Versão dois" in comparison_html
    assert "diff-delete" in comparison_html
    assert "diff-insert" in comparison_html

    assert (
        client.post(
            _editorial_url("content_editorial_submit", content_id=content.pk)
        ).status_code
        == 302
    )
    _force_clinic_client(client, clinic, reviewer)
    assert (
        client.post(
            _editorial_url("content_editorial_approve", content_id=content.pk),
            {"opinion": "Segunda versão aprovada.", "review_valid_days": "30"},
        ).status_code
        == 302
    )
    _force_clinic_client(client, clinic, publisher)
    assert (
        client.post(
            _editorial_url("content_publish", content_id=content.pk)
        ).status_code
        == 302
    )

    upload = SimpleUploadedFile(
        "apoio.png", b"\x89PNG\r\n\x1a\nsafe", content_type="image/png"
    )
    assert (
        client.post(
            _editorial_url("content_editorial_media", content_id=content.pk),
            {"file": upload},
        ).status_code
        == 302
    )
    assert (
        content_models.ContentMedia.objects.for_clinic(clinic.pk)
        .filter(content_id=content.pk)
        .count()
        == 1
    )

    assert (
        client.post(
            _editorial_url("content_editorial_rollback", content_id=content.pk),
            {"target_version": "1"},
        ).status_code
        == 302
    )
    content.refresh_from_db()
    assert content.current_version == 1
    assert (
        client.post(
            _editorial_url("content_editorial_archive", content_id=content.pk)
        ).status_code
        == 302
    )
    content.refresh_from_db()
    assert content.status == content_models.ContentStatus.ARCHIVED


def test_editorial_direct_ids_are_non_enumerating_and_tenant_scoped(
    client: Client,
) -> None:
    clinic_a = ClinicFactory.create()
    clinic_b = ClinicFactory.create()
    admin_a, _reviewer_a, _publisher_a = _clinic_team(clinic_a)
    admin_b, _reviewer_b, _publisher_b = _clinic_team(clinic_b)
    foreign = content_services.start_content(
        clinic_id=clinic_b.pk,
        actor=admin_b,
        slug="segredo-editorial",
        title="Segredo editorial",
        kind=content_models.ContentKind.ARTICLE,
        body="Não enumerar.",
        request_id=uuid4(),
    )
    _force_clinic_client(client, clinic_a, admin_a)

    missing_status = client.get(
        _editorial_url("content_editorial_detail", content_id=uuid4())
    ).status_code
    foreign_status = client.get(
        _editorial_url("content_editorial_detail", content_id=foreign.pk)
    ).status_code
    foreign_post_status = client.post(
        _editorial_url("content_editorial_archive", content_id=foreign.pk)
    ).status_code

    assert missing_status == foreign_status == foreign_post_status == 404


def test_editorial_surface_requires_clinic_admin_role(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _reviewer, _publisher = _clinic_team(clinic)
    therapist = UserFactory.create()
    _credential_for(clinic, therapist, "therapist")
    content = content_services.start_content(
        clinic_id=clinic.pk,
        actor=admin,
        slug="restrito-editorial",
        title="Restrito editorial",
        kind=content_models.ContentKind.ARTICLE,
        body="Somente administração.",
        request_id=uuid4(),
    )
    _force_clinic_client(client, clinic, therapist)

    assert client.get(_editorial_url("content_editorial_index")).status_code == 403
    assert (
        client.get(
            _editorial_url("content_editorial_detail", content_id=content.pk)
        ).status_code
        == 403
    )
    assert (
        client.post(
            _editorial_url("content_editorial_submit", content_id=content.pk)
        ).status_code
        == 403
    )


def test_editorial_create_with_metadata_persists_all_three_fields(
    client: Client,
) -> None:
    clinic = ClinicFactory.create()
    admin, _reviewer, _publisher = _clinic_team(clinic)
    _force_clinic_client(client, clinic, admin)

    created = client.post(
        _editorial_url("content_editorial_create"),
        {
            "slug": "guia-contraindicacoes",
            "title": "Guia com metadados",
            "kind": content_models.ContentKind.ARTICLE,
            "body": "<p>Corpo inicial.</p>",
            "language_code": "pt-BR",
            "audience": "patient",
            "contraindications": "Não usar em casos de hipertensão.",
            "source_reference": "Manual clínico 2026",
            "valid_until": "2026-12-31",
        },
    )

    assert created.status_code == 302
    content = content_models.Content.objects.for_clinic(clinic.pk).get(
        slug="guia-contraindicacoes"
    )
    assert content.contraindications == "Não usar em casos de hipertensão."
    assert content.source_reference == "Manual clínico 2026"
    assert content.valid_until == date(2026, 12, 31)


def test_editorial_metadata_update_changes_fields_for_admin(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _reviewer, _publisher = _clinic_team(clinic)
    content = content_services.start_content(
        clinic_id=clinic.pk,
        actor=admin,
        slug="metadados-editaveis",
        title="Metadados editáveis",
        kind=content_models.ContentKind.ARTICLE,
        body="Corpo.",
        request_id=uuid4(),
    )
    _force_clinic_client(client, clinic, admin)

    response = client.post(
        _editorial_url("content_editorial_metadata", content_id=content.pk),
        {
            "contraindications": "Evitar durante a gestação.",
            "source_reference": "Diretriz nova",
            "valid_until": "2027-01-31",
        },
    )

    assert response.status_code == 302
    content.refresh_from_db()
    assert content.contraindications == "Evitar durante a gestação."
    assert content.source_reference == "Diretriz nova"
    assert content.valid_until == date(2027, 1, 31)


def test_editorial_metadata_update_denied_for_non_admin(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _reviewer, _publisher = _clinic_team(clinic)
    therapist = UserFactory.create()
    _credential_for(clinic, therapist, "therapist")
    content = content_services.start_content(
        clinic_id=clinic.pk,
        actor=admin,
        slug="metadados-protegidos",
        title="Metadados protegidos",
        kind=content_models.ContentKind.ARTICLE,
        body="Corpo.",
        request_id=uuid4(),
    )
    _force_clinic_client(client, clinic, therapist)

    response = client.post(
        _editorial_url("content_editorial_metadata", content_id=content.pk),
        {
            "contraindications": "Tentativa indevida.",
            "source_reference": "Referência indevida.",
            "valid_until": "2027-01-31",
        },
    )

    assert response.status_code == 403


def test_editorial_metadata_update_404_for_foreign_content(client: Client) -> None:
    clinic_a = ClinicFactory.create()
    clinic_b = ClinicFactory.create()
    admin_a, _r_a, _p_a = _clinic_team(clinic_a)
    admin_b, _r_b, _p_b = _clinic_team(clinic_b)
    foreign = content_services.start_content(
        clinic_id=clinic_b.pk,
        actor=admin_b,
        slug="metadados-alheios",
        title="Metadados alheios",
        kind=content_models.ContentKind.ARTICLE,
        body="Corpo.",
        request_id=uuid4(),
    )
    _force_clinic_client(client, clinic_a, admin_a)

    response = client.post(
        _editorial_url("content_editorial_metadata", content_id=foreign.pk),
        {"contraindications": "x", "source_reference": "y"},
    )

    assert response.status_code == 404


def test_editorial_taxonomy_rejects_terms_beyond_model_limit(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _reviewer, _publisher = _clinic_team(clinic)
    _force_clinic_client(client, clinic, admin)
    long_term = "c" * 65

    response = client.post(
        _editorial_url("content_editorial_create"),
        {
            "slug": "taxonomia-longa",
            "title": "Taxonomia longa",
            "kind": content_models.ContentKind.ARTICLE,
            "body": "Corpo.",
            "language_code": "pt-BR",
            "audience": "patient",
            "categories": long_term,
            "tags": long_term,
        },
    )

    assert response.status_code == 200
    assert (
        not content_models.Content.objects.for_clinic(clinic.pk)
        .filter(slug="taxonomia-longa")
        .exists()
    )
    assert content_models.ContentCategory.objects.for_clinic(clinic.pk).count() == 0
    assert content_models.ContentTag.objects.for_clinic(clinic.pk).count() == 0


def test_editorial_version_schedules_using_clinic_timezone(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _reviewer, _publisher = _clinic_team(clinic)
    content = content_services.start_content(
        clinic_id=clinic.pk,
        actor=admin,
        slug="agendamento-fuso",
        title="Agendamento por fuso",
        kind=content_models.ContentKind.ARTICLE,
        body="Corpo.",
        request_id=uuid4(),
    )
    configuration = ClinicConfiguration.infrastructure_objects.create(
        clinic=clinic,
        legal_name="Clínica Fuso",
        display_name="Clínica Fuso",
        administrative_email="fuso@example.test",
        address_line_1="Rua um",
        city="Recife",
        region="PE",
        postal_code="50000-000",
        country_code="BR",
        timezone_name="America/New_York",
    )
    assert configuration.timezone_name == "America/New_York"
    _force_clinic_client(client, clinic, admin)

    with override_settings(TIME_ZONE="America/Sao_Paulo"):
        response = client.post(
            _editorial_url("content_editorial_version", content_id=content.pk),
            {"body": "Corpo agendado.", "scheduled_for": "2026-01-15 09:00"},
        )

    assert response.status_code == 302
    content.refresh_from_db()
    version = content_models.ContentVersion.objects.for_clinic(clinic.pk).get(
        content_id=content.pk, version=content.current_version
    )
    assert version.scheduled_for is not None
    # 09:00 in America/New_York (EST, UTC-5) is 14:00 UTC.
    assert version.scheduled_for.utcoffset() == timedelta(0)
    assert version.scheduled_for.astimezone(UTC).hour == 14


@override_settings(TIME_ZONE="America/Sao_Paulo")
def test_editorial_version_schedules_across_dst_boundary(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _reviewer, _publisher = _clinic_team(clinic)
    content = content_services.start_content(
        clinic_id=clinic.pk,
        actor=admin,
        slug="agendamento-dst",
        title="Agendamento com DST",
        kind=content_models.ContentKind.ARTICLE,
        body="Corpo.",
        request_id=uuid4(),
    )
    ClinicConfiguration.infrastructure_objects.create(
        clinic=clinic,
        legal_name="Clínica DST",
        display_name="Clínica DST",
        administrative_email="dst@example.test",
        address_line_1="Rua dois",
        city="Recife",
        region="PE",
        postal_code="50000-000",
        country_code="BR",
        timezone_name="America/New_York",
    )
    _force_clinic_client(client, clinic, admin)

    response = client.post(
        _editorial_url("content_editorial_version", content_id=content.pk),
        # 2026-07-15 09:00 is EDT (UTC-4): 13:00 UTC, not the winter 14:00 UTC.
        {"body": "Corpo DST.", "scheduled_for": "2026-07-15 09:00"},
    )

    assert response.status_code == 302
    version = content_models.ContentVersion.objects.for_clinic(clinic.pk).get(
        content_id=content.pk, version=2
    )
    assert version.scheduled_for is not None
    assert version.scheduled_for.utcoffset() == timedelta(0)
    assert version.scheduled_for.astimezone(UTC).hour == 13


def test_editorial_block_editor_preserves_order_and_semantics(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _reviewer, _publisher = _clinic_team(clinic)
    _force_clinic_client(client, clinic, admin)

    created = client.post(
        _editorial_url("content_editorial_create"),
        {
            "slug": "blocos-ordenados",
            "title": "Blocos ordenados",
            "kind": content_models.ContentKind.ARTICLE,
            "block_type": ["heading", "paragraph", "list_item"],
            "block_text": ["Título principal", "Texto corrido.", "Item da lista."],
            "language_code": "pt-BR",
            "audience": "patient",
        },
    )

    assert created.status_code == 302
    content = content_models.Content.objects.for_clinic(clinic.pk).get(
        slug="blocos-ordenados"
    )
    version = content_models.ContentVersion.objects.for_clinic(clinic.pk).get(
        content_id=content.pk
    )
    assert "<h2>Título principal</h2>" in version.body
    assert "<p>Texto corrido.</p>" in version.body
    assert "<li>Item da lista.</li>" in version.body
    assert re.search(
        r"<h2>Título principal</h2>.*<p>Texto corrido.</p>.*<li>Item",
        version.body,
        re.S,
    )

    preview = client.get(
        _editorial_url("content_editorial_preview", content_id=content.pk, version=1)
    )
    preview_html = preview.content.decode()
    assert preview.status_code == 200
    heading_pos = preview_html.find("<h2>Título principal</h2>")
    paragraph_pos = preview_html.find("<p>Texto corrido.</p>")
    assert heading_pos != -1 and paragraph_pos != -1
    assert heading_pos < paragraph_pos


def test_editorial_stored_href_injection_is_neutralized_end_to_end(
    client: Client,
) -> None:
    clinic = ClinicFactory.create()
    admin, reviewer, publisher = _clinic_team(clinic)
    payload = '<a href="https://safe.test/&quot; onmouseover=&quot;alert(1)">click</a>'
    content = _publish_article(
        clinic,
        admin,
        reviewer,
        publisher,
        slug="href-injetado",
        title="Href injetado",
        body=payload,
    )
    _force_clinic_client(client, clinic, admin)

    version = content_models.ContentVersion.objects.for_clinic(clinic.pk).get(
        content_id=content.pk, version=1
    )
    stored_body = version.body
    assert "onmouseover" not in stored_body
    assert "alert(1)" not in stored_body
    assert "https://safe.test/" in stored_body
    assert "click" in stored_body

    preview = client.get(
        _editorial_url("content_editorial_preview", content_id=content.pk, version=1)
    )
    preview_html = preview.content.decode()
    assert preview.status_code == 200
    assert "onmouseover" not in preview_html
    assert "alert(1)" not in preview_html
    assert "https://safe.test/" in preview_html

    detail = client.get(reverse("content_detail", kwargs={"slug": "href-injetado"}))
    detail_html = detail.content.decode()
    assert detail.status_code == 200
    assert "onmouseover" not in detail_html
    assert "alert(1)" not in detail_html
    assert "https://safe.test/" in detail_html
