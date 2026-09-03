"""Forms for finance flows, labeled in PT-BR."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

from django import forms


class ServicePriceForm(forms.Form):
    """Collect one effective service price."""

    service = forms.ChoiceField(label="Serviço")
    amount = forms.DecimalField(
        label="Valor (R$)", min_value=Decimal("0.00"), decimal_places=2
    )
    currency = forms.CharField(label="Moeda", initial="BRL", max_length=3)
    valid_from = forms.DateField(
        label="Vigência inicial", widget=forms.DateInput(attrs={"type": "date"})
    )
    valid_until = forms.DateField(
        label="Vigência final (opcional)",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(
        self,
        *args: Any,
        service_choices: list[tuple[str, str]],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        cast(forms.ChoiceField, self.fields["service"]).choices = service_choices


class ChargeCancelForm(forms.Form):
    """Collect a cancellation reason."""

    reason = forms.CharField(label="Motivo", max_length=255)
