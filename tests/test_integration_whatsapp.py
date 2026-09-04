"""Tests for WhatsApp consent, templates and timeline (8.13.2)."""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from clinics.models import Clinic, ClinicMembership
from integrations.contracts import FakeWhatsAppAdapter
from integrations.whatsapp import (
    create_whatsapp_template,
    has_valid_whatsapp_consent,
    parse_inbound_action,
    process_inbound_whatsapp_reply,
    record_whatsapp_consent,
    render_whatsapp_template,
    revoke_whatsapp_consent,
    send_whatsapp_message,
    update_whatsapp_delivery_status,
)
from integrations.whatsapp_models import (
    WhatsAppConsentStatus,
    WhatsAppDeliveryStatus,
    WhatsAppInboundMessage,
    WhatsAppParsedAction,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica WhatsApp Teste")


@pytest.fixture
def patient_user(test_clinic: Clinic):
    user = UserFactory.create(email="paciente.wa@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.mark.django_db
def test_whatsapp_consent_lifecycle_and_verification(
    test_clinic: Clinic, patient_user
) -> None:
    """Consent is recorded, checked, and immediately stops sends when revoked."""
    phone = "+5581987654321"

    # Initially no consent
    assert not has_valid_whatsapp_consent(
        clinic_id=test_clinic.id, phone_number=phone, purpose="appointment_reminders"
    )

    # Grant consent
    consent = record_whatsapp_consent(
        clinic_id=test_clinic.id,
        phone_number=phone,
        purpose="appointment_reminders",
        patient_user_id=patient_user.id,
        consent_text="Concordo em receber lembretes de consultas via WhatsApp.",
        actor_id=patient_user.id,
    )
    assert consent.status == WhatsAppConsentStatus.ACTIVE
    assert has_valid_whatsapp_consent(
        clinic_id=test_clinic.id, phone_number=phone, purpose="appointment_reminders"
    )

    # Revoke consent
    revoked = revoke_whatsapp_consent(
        clinic_id=test_clinic.id,
        phone_number=phone,
        purpose="appointment_reminders",
        reason="Usuário solicitou cancelamento",
        actor_id=patient_user.id,
    )
    assert revoked.status == WhatsAppConsentStatus.REVOKED
    assert not has_valid_whatsapp_consent(
        clinic_id=test_clinic.id, phone_number=phone, purpose="appointment_reminders"
    )


@pytest.mark.django_db
def test_whatsapp_template_catalog_blocks_clinical_terms(test_clinic: Clinic) -> None:
    """Templates are strictly administrative and reject clinical content."""
    # Valid administrative template
    valid_template = create_whatsapp_template(
        clinic_id=test_clinic.id,
        name="lembrete_consulta",
        body_template=(
            "Olá {nome}, seu agendamento na clínica {clinica} está "
            "marcado para {data} às {horario}."
        ),
    )
    assert valid_template.name == "lembrete_consulta"

    rendered = render_whatsapp_template(
        template=valid_template,
        parameters={
            "nome": "Carla",
            "clinica": "Espaço Cuidar",
            "data": "10/09/2026",
            "horario": "14:00",
        },
    )
    assert "Carla" in rendered
    assert "14:00" in rendered

    # Template with clinical terms must be rejected
    with pytest.raises(ValidationError, match="termos clínicos"):
        create_whatsapp_template(
            clinic_id=test_clinic.id,
            name="template_invalido_diagnostico",
            body_template=(
                "Olá {nome}, lembrete para sua sessão de tratamento de "
                "depressão e ansiedade."
            ),
        )

    with pytest.raises(ValidationError, match="termos clínicos"):
        create_whatsapp_template(
            clinic_id=test_clinic.id,
            name="template_invalido_medicamento",
            body_template="Lembrete para tomar seu medicamento psiquiátrico.",
        )


@pytest.mark.django_db
def test_whatsapp_send_enforces_consent_and_updates_timeline(
    test_clinic: Clinic, patient_user
) -> None:
    """Outbound dispatch enforces active consent and tracks delivery status."""
    phone = "+5581999998888"
    adapter = FakeWhatsAppAdapter()

    create_whatsapp_template(
        clinic_id=test_clinic.id,
        name="aviso_horario",
        body_template="Olá {nome}, confirmamos seu horário para {data}.",
    )

    # 1. Attempt send without consent -> Blocked
    with pytest.raises(PermissionDenied, match="Consentimento para WhatsApp ausente"):
        send_whatsapp_message(
            clinic_id=test_clinic.id,
            recipient_phone=phone,
            template_name="aviso_horario",
            parameters={"nome": "Ana", "data": "15/09/2026"},
            adapter=adapter,
        )

    # 2. Grant consent and send
    record_whatsapp_consent(
        clinic_id=test_clinic.id,
        phone_number=phone,
        patient_user_id=patient_user.id,
    )

    timeline = send_whatsapp_message(
        clinic_id=test_clinic.id,
        recipient_phone=phone,
        template_name="aviso_horario",
        parameters={"nome": "Ana", "data": "15/09/2026"},
        adapter=adapter,
        fallback_channel="email",
    )

    assert timeline.status == WhatsAppDeliveryStatus.SENT
    assert timeline.provider_message_id.startswith("wamid.fake.")
    assert timeline.masked_phone == "+558*****88"

    # 3. Simulate delivery receipts
    updated = update_whatsapp_delivery_status(
        provider_message_id=timeline.provider_message_id,
        status="delivered",
    )
    assert updated is not None
    assert updated.status == WhatsAppDeliveryStatus.DELIVERED
    assert updated.delivered_at is not None

    read = update_whatsapp_delivery_status(
        provider_message_id=timeline.provider_message_id,
        status="read",
    )
    assert read is not None
    assert read.status == WhatsAppDeliveryStatus.READ
    assert read.read_at is not None


@pytest.mark.django_db
def test_whatsapp_inbound_parsing_and_opt_out_action(test_clinic: Clinic) -> None:
    """Inbound messages parse intent; 'PARAR' immediately revokes consent."""
    phone = "+5581977776666"
    record_whatsapp_consent(
        clinic_id=test_clinic.id,
        phone_number=phone,
    )
    assert has_valid_whatsapp_consent(clinic_id=test_clinic.id, phone_number=phone)

    # Test parsing intents
    assert parse_inbound_action("1") == WhatsAppParsedAction.CONFIRM
    assert parse_inbound_action("Sim, confirmo") == WhatsAppParsedAction.CONFIRM
    assert parse_inbound_action("2") == WhatsAppParsedAction.RESCHEDULE
    assert parse_inbound_action("0") == WhatsAppParsedAction.CANCEL
    assert parse_inbound_action("Não poderei ir") == WhatsAppParsedAction.CANCEL
    assert parse_inbound_action("PARAR") == WhatsAppParsedAction.OPT_OUT
    assert parse_inbound_action("sair") == WhatsAppParsedAction.OPT_OUT
    assert parse_inbound_action("mensagem qualquer") == WhatsAppParsedAction.UNKNOWN

    # Process inbound OPT-OUT
    inbound = process_inbound_whatsapp_reply(
        clinic_id=test_clinic.id,
        sender_phone=phone,
        external_message_id="msg_optout_001",
        raw_text="Por favor parar de enviar mensagens",
    )
    assert inbound.action_parsed == WhatsAppParsedAction.OPT_OUT
    assert inbound.processed is True

    # Consent must now be revoked
    assert not has_valid_whatsapp_consent(clinic_id=test_clinic.id, phone_number=phone)

    # Inbound deduplication
    duplicate = process_inbound_whatsapp_reply(
        clinic_id=test_clinic.id,
        sender_phone=phone,
        external_message_id="msg_optout_001",
        raw_text="Por favor parar de enviar mensagens",
    )
    assert duplicate.id == inbound.id
    count = WhatsAppInboundMessage.objects.filter(
        external_message_id="msg_optout_001"
    ).count()
    assert count == 1
