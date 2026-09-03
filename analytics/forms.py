"""Forms for analytics views, labeled in PT-BR."""

from __future__ import annotations

from django import forms


class ReportPeriodForm(forms.Form):
    """Collect a report period."""

    period_start = forms.DateField(
        label="Início do período",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    period_end = forms.DateField(
        label="Fim do período",
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def clean(self) -> None:
        super().clean()
        start = self.cleaned_data.get("period_start")
        end = self.cleaned_data.get("period_end")
        if start and end and end < start:
            self.add_error("period_end", "O fim deve ser igual ou posterior ao início.")
