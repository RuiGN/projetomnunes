"""Forms for patient goals in PT-BR."""

from __future__ import annotations

from django import forms

from .models import Goal


class GoalForm(forms.Form):
    """Collect one patient goal with small steps in PT-BR."""

    title = forms.CharField(
        label="Qual é a sua meta?",
        max_length=255,
        help_text="Ex.: Retomar caminhadas diárias",
    )
    description = forms.CharField(
        label="Detalhes (opcional)",
        max_length=4000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Opcional. Máximo de 4000 caracteres.",
    )
    horizon = forms.ChoiceField(
        label="Horizonte de tempo",
        choices=Goal.Horizon.choices,
        initial=Goal.Horizon.SHORT,
        widget=forms.RadioSelect,
        required=True,
    )
    priority = forms.TypedChoiceField(
        label="Prioridade",
        choices=[(str(v), label) for v, label in Goal.Priority.choices],
        coerce=int,
        initial=str(Goal.Priority.MEDIUM),
        widget=forms.RadioSelect,
        required=True,
    )
    due_date = forms.DateField(
        label="Prazo (opcional)",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Você pode alterar ou remover o prazo quando quiser, sem penalidade.",
    )
    steps_raw = forms.CharField(
        label="Pequenas etapas",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": (
                    "Uma etapa por linha. Ex.:\nSepare os tênis\nCaminhe 5 minutos hoje"
                ),
            }
        ),
        help_text=(
            "Uma etapa por linha. Pequenas etapas tornam a meta mais fácil de seguir."
        ),
    )
    visibility = forms.ChoiceField(
        label="Compartilhamento",
        choices=Goal.Visibility.choices,
        initial=Goal.Visibility.PRIVATE,
        widget=forms.RadioSelect,
        required=True,
        help_text=(
            "Verde = Compartilhável com terapeuta; Amarelo = Perguntar antes;"
            " Vermelho = Somente eu (privado)."
        ),
    )

    def clean_title(self) -> str:
        value = (self.cleaned_data.get("title") or "").strip()
        if not value:
            raise forms.ValidationError("Dê um título à sua meta.")
        return value

    def clean_steps_raw(self) -> list[str]:
        raw = self.cleaned_data.get("steps_raw") or ""
        steps = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(steps) > 50:
            raise forms.ValidationError("Uma meta pode ter no máximo 50 etapas.")
        return steps
