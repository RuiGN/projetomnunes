"""Forms for the emotional journal and check-in domain."""

from __future__ import annotations

from django import forms

from .models import (
    CONTEXT_MAX_LENGTH,
    DETAIL_MAX_LENGTH,
    JournalEntry,
)


class JournalEntryForm(forms.Form):
    """Collect one patient diary record in PT-BR with accessibility metadata."""

    mood = forms.TypedChoiceField(
        label="Como você está se sentindo?",
        choices=JournalEntry.Mood.choices,
        coerce=int,
        widget=forms.RadioSelect,
        help_text=(
            "Selecione como você avalia seu humor geral neste momento "
            "(1 = Muito mal a 5 = Muito bem)."
        ),
        required=True,
    )
    emotions = forms.MultipleChoiceField(
        label="Quais emoções você identifica?",
        choices=JournalEntry.Emotion.choices,
        widget=forms.CheckboxSelectMultiple,
        help_text="Você pode selecionar mais de uma emoção.",
        required=False,
    )
    intensity = forms.IntegerField(
        label="Intensidade emocional (1 a 5)",
        min_value=1,
        max_value=5,
        initial=3,
        help_text="1 = muito leve, 5 = muito intensa",
        required=True,
    )
    context = forms.CharField(
        label="Relato do diário",
        max_length=CONTEXT_MAX_LENGTH,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": (
                    "Descreva o que aconteceu ou como você está se sentindo..."
                ),
            }
        ),
        help_text=f"Máximo de {CONTEXT_MAX_LENGTH} caracteres.",
        required=True,
    )
    triggers = forms.CharField(
        label="Gatilhos",
        max_length=DETAIL_MAX_LENGTH,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "placeholder": (
                    "Situações, pensamentos ou eventos que desencadearam este momento"
                    " (opcional)"
                ),
            }
        ),
        help_text=f"Opcional. Máximo de {DETAIL_MAX_LENGTH} caracteres.",
        required=False,
    )
    reactions = forms.CharField(
        label="Reações físicas",
        max_length=DETAIL_MAX_LENGTH,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "placeholder": (
                    "Ex.: tensão muscular, respiração curta, aperto no peito (opcional)"
                ),
            }
        ),
        help_text=f"Opcional. Máximo de {DETAIL_MAX_LENGTH} caracteres.",
        required=False,
    )
    strategies = forms.CharField(
        label="O que me ajudou",
        max_length=DETAIL_MAX_LENGTH,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "placeholder": (
                    "Ações, pensamentos ou técnicas que ajudaram a lidar com a situação"
                    " (opcional)"
                ),
            }
        ),
        help_text=f"Opcional. Máximo de {DETAIL_MAX_LENGTH} caracteres.",
        required=False,
    )
    visibility = forms.ChoiceField(
        label="Compartilhamento",
        choices=JournalEntry.Visibility.choices,
        widget=forms.RadioSelect,
        initial=JournalEntry.Visibility.PRIVATE,
        help_text=(
            "Verde = Compartilhável com terapeuta; Amarelo = Perguntar antes de"
            " compartilhar; Vermelho = Somente eu (privado)."
        ),
        required=True,
    )

    def clean_context(self) -> str:
        value = (self.cleaned_data.get("context") or "").strip()
        if not value:
            raise forms.ValidationError("Descreva o relato do diário.")
        if len(value) > CONTEXT_MAX_LENGTH:
            raise forms.ValidationError(
                "O relato do diário deve ter no máximo"
                f" {CONTEXT_MAX_LENGTH} caracteres."
            )
        return value

    def clean_triggers(self) -> str:
        value = (self.cleaned_data.get("triggers") or "").strip()
        if len(value) > DETAIL_MAX_LENGTH:
            raise forms.ValidationError(
                f"O campo gatilhos deve ter no máximo {DETAIL_MAX_LENGTH} caracteres."
            )
        return value

    def clean_reactions(self) -> str:
        value = (self.cleaned_data.get("reactions") or "").strip()
        if len(value) > DETAIL_MAX_LENGTH:
            raise forms.ValidationError(
                f"O campo reações deve ter no máximo {DETAIL_MAX_LENGTH} caracteres."
            )
        return value

    def clean_strategies(self) -> str:
        value = (self.cleaned_data.get("strategies") or "").strip()
        if len(value) > DETAIL_MAX_LENGTH:
            raise forms.ValidationError(
                "O campo estratégias deve ter no máximo"
                f" {DETAIL_MAX_LENGTH} caracteres."
            )
        return value


class JournalFilterForm(forms.Form):
    """Filter parameters for patient journal history in PT-BR."""

    PERIOD_CHOICES = (
        ("7d", "Últimos 7 dias"),
        ("30d", "Últimos 30 dias"),
        ("90d", "Últimos 90 dias"),
        ("all", "Todo o histórico"),
    )

    period = forms.ChoiceField(
        label="Período",
        choices=PERIOD_CHOICES,
        required=False,
        initial="30d",
    )
    emotion = forms.ChoiceField(
        label="Emoção",
        choices=[("", "Todas as emoções"), *JournalEntry.Emotion.choices],
        required=False,
    )
    mood = forms.ChoiceField(
        label="Humor",
        choices=[
            ("", "Todos os humores"),
            *[(str(val), label) for val, label in JournalEntry.Mood.choices],
        ],
        required=False,
    )
