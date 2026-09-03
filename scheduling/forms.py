"""Forms for scheduling flows, labeled in PT-BR."""

from __future__ import annotations

from typing import Any, cast

from django import forms

from .models import ConversationKind, ReminderChannel, ReminderType

DATETIME_INPUT_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]


class AppointmentRequestForm(forms.Form):
    """Collect a patient's consultation request against an open slot."""

    service = forms.ChoiceField(label="Tipo de consulta")
    professional = forms.ChoiceField(label="Profissional")
    unit = forms.ChoiceField(label="Unidade")
    start_at = forms.DateTimeField(
        label="Data e horário",
        input_formats=DATETIME_INPUT_FORMATS,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "step": 1800}),
    )

    def __init__(
        self,
        *args: Any,
        service_choices: list[tuple[str, str]],
        professional_choices: list[tuple[str, str]],
        unit_choices: list[tuple[str, str]],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        cast(forms.ChoiceField, self.fields["service"]).choices = service_choices
        cast(
            forms.ChoiceField, self.fields["professional"]
        ).choices = professional_choices
        cast(forms.ChoiceField, self.fields["unit"]).choices = unit_choices


class AppointmentRescheduleForm(forms.Form):
    """Collect a proposed new start time for one appointment."""

    start_at = forms.DateTimeField(
        label="Novo data e horário",
        input_formats=DATETIME_INPUT_FORMATS,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "step": 1800}),
    )


class ReminderPreferenceForm(forms.Form):
    """Collect one patient reminder preference."""

    reminder_type = forms.ChoiceField(
        label="Tipo de lembrete", choices=ReminderType.choices
    )
    channel = forms.ChoiceField(label="Canal", choices=ReminderChannel.choices)
    enabled = forms.BooleanField(label="Ativado", required=False)
    advance_minutes = forms.IntegerField(label="Antecedência (minutos)", min_value=0)
    silence_start = forms.TimeField(
        label="Início do horário de silêncio (opcional)",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    silence_end = forms.TimeField(
        label="Fim do horário de silêncio (opcional)",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    timezone_name = forms.CharField(label="Fuso horário", required=False)
    max_daily = forms.IntegerField(
        label="Frequência máxima diária", min_value=1, max_value=24
    )


class ConversationForm(forms.Form):
    """Collect one conversation's channel, subject and bound participants."""

    kind = forms.ChoiceField(label="Tipo de conversa", choices=ConversationKind.choices)
    subject = forms.CharField(
        label="Assunto (opcional)", max_length=255, required=False
    )
    participant_ids = forms.MultipleChoiceField(label="Participantes")

    def __init__(
        self, *args: Any, participant_choices: list[tuple[str, str]], **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        cast(
            forms.ChoiceField, self.fields["participant_ids"]
        ).choices = participant_choices


class MessageForm(forms.Form):
    """Collect one immutable message body."""

    body = forms.CharField(
        label="Mensagem",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Este canal não atende emergências.",
    )


class AppointmentActionForm(forms.Form):
    """Carry an optional reason for cancellation."""

    reason = forms.CharField(label="Motivo (opcional)", required=False, max_length=255)


class WaitlistEntryForm(forms.Form):
    """Collect one waitlist request with period and unit preference."""

    patient_profile = forms.ChoiceField(label="Paciente")
    unit = forms.ChoiceField(label="Unidade")
    service = forms.ChoiceField(label="Serviço")
    preferred_period = forms.CharField(
        label="Período preferido (opcional)", required=False, max_length=32
    )
    contact_note = forms.CharField(
        label="Contato (opcional)", required=False, max_length=255
    )

    def __init__(
        self,
        *args: Any,
        patient_choices: list[tuple[str, str]],
        unit_choices: list[tuple[str, str]],
        service_choices: list[tuple[str, str]],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        cast(
            forms.ChoiceField, self.fields["patient_profile"]
        ).choices = patient_choices
        cast(forms.ChoiceField, self.fields["unit"]).choices = unit_choices
        cast(forms.ChoiceField, self.fields["service"]).choices = service_choices


class UnitForm(forms.Form):
    """Collect one unit's operational identity."""

    name = forms.CharField(label="Nome", max_length=255)
    timezone_name = forms.CharField(
        label="Fuso horário", initial="America/Sao_Paulo", max_length=64
    )


class RoomForm(forms.Form):
    """Collect one room's name inside a unit."""

    unit = forms.ChoiceField(label="Unidade")
    name = forms.CharField(label="Nome", max_length=255)

    def __init__(
        self, *args: Any, unit_choices: list[tuple[str, str]], **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        cast(forms.ChoiceField, self.fields["unit"]).choices = unit_choices
