"""Forms for the stepped patient onboarding flow."""

from typing import Any

from django import forms


class PatientGoalsForm(forms.Form):
    """Collect declared personal goals, one per line."""

    goals = forms.CharField(
        label="Objetivos pessoais",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 6, "placeholder": "Um objetivo por linha."}
        ),
    )

    def clean_goals(self) -> list[str]:
        raw = self.cleaned_data["goals"]
        return [line.strip() for line in raw.splitlines() if line.strip()]


class PatientPreferencesForm(forms.Form):
    """Collect contact and reminder preferences as reviewable choices."""

    contact_preferences = forms.MultipleChoiceField(
        label="Como você prefere ser contatado(a)?",
        required=False,
        choices=(
            ("email", "E-mail"),
            ("phone", "Telefone"),
            ("whatsapp", "WhatsApp"),
        ),
        widget=forms.CheckboxSelectMultiple,
    )
    reminder_windows = forms.MultipleChoiceField(
        label="Melhores horários para lembretes",
        required=False,
        choices=(
            ("morning", "Manhã"),
            ("afternoon", "Tarde"),
            ("evening", "Noite"),
        ),
        widget=forms.CheckboxSelectMultiple,
    )

    def clean(self) -> dict[str, Any]:
        cleaned = dict(super().clean() or {})
        cleaned["contact_preferences"] = {
            channel: channel in (cleaned.get("contact_preferences") or [])
            for channel in ("email", "phone", "whatsapp")
        }
        cleaned["reminder_windows"] = {
            window: window in (cleaned.get("reminder_windows") or [])
            for window in ("morning", "afternoon", "evening")
        }
        return cleaned
