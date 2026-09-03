"""Server-rendered PT-BR forms for account authentication flows."""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from clinics.services import membership_role_choices


class LoginForm(forms.Form):
    """Collect credentials without encoding account-existence distinctions."""

    email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    password = forms.CharField(
        label="Senha",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class PasswordRecoveryForm(forms.Form):
    """Collect a recovery identity using a neutral response contract."""

    email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )


class PasswordResetForm(forms.Form):
    """Validate a new credential and its explicit confirmation."""

    new_password = forms.CharField(
        label="Nova senha",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    confirm_password = forms.CharField(
        label="Confirme a nova senha",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean(self) -> dict[str, Any]:
        """Require matching credentials and apply configured Django validators."""
        cleaned: dict[str, Any] = super().clean() or {}
        password = cleaned.get("new_password")
        confirmation = cleaned.get("confirm_password")
        if password and confirmation and password != confirmation:
            self.add_error(
                "confirm_password",
                "As senhas informadas não coincidem.",
            )
            return cleaned
        if isinstance(password, str):
            try:
                validate_password(password)
            except ValidationError as error:
                self.add_error("new_password", error)
        return cleaned


class MFACodeForm(forms.Form):
    """Collect a TOTP or single-use recovery credential."""

    code = forms.CharField(
        label="Código de verificação",
        min_length=6,
        max_length=32,
        strip=True,
        widget=forms.TextInput(
            attrs={"autocomplete": "one-time-code", "inputmode": "numeric"}
        ),
    )


class SensitiveActionReauthenticationForm(forms.Form):
    """Collect the current password immediately before a high-impact action."""

    password = forms.CharField(
        label="Senha atual",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class AdministrativeMFAResetForm(SensitiveActionReauthenticationForm):
    """Collect a target and justification for an auditable MFA reset."""

    target_user_id = forms.UUIDField(label="Identificador da pessoa")
    reason = forms.CharField(
        label="Justificativa",
        min_length=10,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 4}),
    )


class InvitationIssueForm(forms.Form):
    """Collect the bounded tenant role and expiry for one invitation."""

    recipient_email = forms.EmailField(label="E-mail da pessoa convidada")
    initial_role = forms.ChoiceField(
        label="Papel inicial",
        choices=membership_role_choices(),
    )
    expires_in_hours = forms.IntegerField(
        label="Validade em horas",
        min_value=1,
        max_value=168,
        initial=24,
    )


class InvitationAcceptanceForm(forms.Form):
    """Collect a new invited identity without weakening password validation."""

    first_name = forms.CharField(label="Nome", max_length=150)
    last_name = forms.CharField(label="Sobrenome", max_length=150)
    password = forms.CharField(
        label="Senha",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    confirm_password = forms.CharField(
        label="Confirme a senha",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean(self) -> dict[str, Any]:
        """Require matching credentials before the service validates strength."""
        cleaned: dict[str, Any] = super().clean() or {}
        password = cleaned.get("password")
        confirmation = cleaned.get("confirm_password")
        if password and confirmation and password != confirmation:
            self.add_error("confirm_password", "As senhas informadas não coincidem.")
        return cleaned
