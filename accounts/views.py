"""Public HTTP views for authentication and credential recovery."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import EmailMultiAlternatives
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods, require_POST

from clinics.services import CLINIC_SESSION_KEY

from .forms import (
    AdministrativeMFAResetForm,
    InvitationAcceptanceForm,
    InvitationIssueForm,
    LoginForm,
    MFACodeForm,
    PasswordRecoveryForm,
    PasswordResetForm,
    SensitiveActionReauthenticationForm,
)
from .models import AccountSession, User, UserMFA
from .services import (
    GENERIC_LOGIN_ERROR,
    GENERIC_RECOVERY_RESPONSE,
    LoginRateLimitedError,
    LoginRejectedError,
    MFAAttemptRateLimitedError,
    RecoveryRateLimitedError,
    SensitiveActionRateLimitedError,
    accept_invitation,
    administratively_reset_mfa,
    build_totp_key_uri,
    build_totp_qr_data_uri,
    confirm_totp_enrollment,
    consume_mfa_code,
    invitation_clinic_id,
    issue_invitation,
    login_user,
    logout_user,
    password_reset_identity,
    reauthenticate_sensitive_action,
    request_password_recovery,
    reset_password,
    revoke_account_session,
    revoke_invitation,
    revoke_other_sessions,
    start_totp_enrollment,
)


def _form_response(
    request: HttpRequest,
    *,
    form: (
        AdministrativeMFAResetForm
        | InvitationAcceptanceForm
        | InvitationIssueForm
        | LoginForm
        | MFACodeForm
        | PasswordRecoveryForm
        | PasswordResetForm
    ),
    title: str,
    description: str,
    submit_label: str,
    status: int = 200,
    secondary_url: str | None = None,
    secondary_label: str | None = None,
) -> TemplateResponse:
    """Render the shared accessible authentication form shell."""
    return TemplateResponse(
        request,
        "accounts/auth_form.html",
        {
            "page_title": title,
            "title": title,
            "description": description,
            "form": form,
            "submit_label": submit_label,
            "secondary_url": secondary_url,
            "secondary_label": secondary_label,
        },
        status=status,
    )


def _safe_local_next(request: HttpRequest, value: object) -> str | None:
    """Return an application-local destination or reject the supplied value."""
    if (
        isinstance(value, str)
        and value.startswith("/")
        and not value.startswith("//")
        and url_has_allowed_host_and_scheme(
            value,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
    ):
        return value
    return None


@require_http_methods(["GET", "POST"])
def account_login(request: HttpRequest) -> HttpResponse:
    """Authenticate with a canonical e-mail and select one authorized clinic."""
    form = LoginForm(request.POST or None)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            login_user(
                request=request,
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
            )
        except LoginRateLimitedError:
            form.add_error(None, GENERIC_LOGIN_ERROR)
            status = 429
        except LoginRejectedError:
            form.add_error(None, GENERIC_LOGIN_ERROR)
        else:
            next_url = _safe_local_next(request, request.GET.get("next"))
            if next_url is not None:
                return redirect(next_url)
            return redirect("workspace_vertical")
    response = _form_response(
        request,
        form=form,
        title="Entrar na plataforma",
        description="Use seu e-mail e sua senha para acessar uma clínica autorizada.",
        submit_label="Entrar",
        status=status,
        secondary_url=reverse("password_recovery"),
        secondary_label="Esqueci minha senha",
    )
    if status == 429:
        response.headers["Retry-After"] = str(
            max(1, int(settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS))
        )
    return response


@require_POST
def account_logout(request: HttpRequest) -> HttpResponse:
    """End the current session through a POST-only auditable action."""
    logout_user(request=request)
    return redirect("account_login")


def _active_clinic_id(request: HttpRequest) -> UUID:
    """Resolve the session tenant; domain services reauthorize every action."""
    try:
        return UUID(str(request.session.get(CLINIC_SESSION_KEY)))
    except (TypeError, ValueError, AttributeError) as error:
        raise PermissionDenied("Active clinic is required.") from error


@login_required
@require_POST
def administrative_mfa_reset(request: HttpRequest) -> HttpResponse:
    """Reset another member's MFA after current-password reauthentication."""
    actor = request.user
    if not isinstance(actor, User):
        raise PermissionDenied
    form = AdministrativeMFAResetForm(request.POST)
    try:
        reauthenticated = form.is_valid() and reauthenticate_sensitive_action(
            actor=actor,
            password=form.cleaned_data.get("password", ""),
        )
    except SensitiveActionRateLimitedError:
        form.add_error("password", "Muitas tentativas. Tente novamente mais tarde.")
        response = _form_response(
            request,
            form=form,
            title="Redefinir autenticação multifator",
            description="Confirme a ação sensível e registre a justificativa.",
            submit_label="Redefinir MFA",
            status=429,
        )
        response.headers["Retry-After"] = str(
            settings.SENSITIVE_REAUTH_RATE_LIMIT_WINDOW_SECONDS
        )
        return response
    if not reauthenticated:
        form.add_error("password", "Não foi possível confirmar sua senha atual.")
        return _form_response(
            request,
            form=form,
            title="Redefinir autenticação multifator",
            description="Confirme a ação sensível e registre a justificativa.",
            submit_label="Redefinir MFA",
            status=400,
        )
    target_user = User.objects.filter(pk=form.cleaned_data["target_user_id"]).first()
    if target_user is None:
        raise PermissionDenied
    administratively_reset_mfa(
        clinic_id=_active_clinic_id(request),
        actor=actor,
        target_user=target_user,
        reason=form.cleaned_data["reason"],
    )
    return redirect("workspace_vertical")


@login_required
@require_http_methods(["GET", "POST"])
def invitation_issue(request: HttpRequest) -> HttpResponse:
    """Issue and deliver a single-use clinic invitation in PT-BR."""
    actor = request.user
    if not isinstance(actor, User):
        raise PermissionDenied
    form = InvitationIssueForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        issued = issue_invitation(
            clinic_id=_active_clinic_id(request),
            issuer=actor,
            recipient_email=form.cleaned_data["recipient_email"],
            initial_role=form.cleaned_data["initial_role"],
            expires_at=timezone.now()
            + timedelta(hours=form.cleaned_data["expires_in_hours"]),
        )
        path = reverse(
            "invitation_accept",
            kwargs={"raw_token": issued.raw_token},
        )
        message = EmailMultiAlternatives(
            subject="Convite para acessar a clínica",
            body=(
                "Você recebeu um convite para acessar a clínica.\n\n"
                f"Acesse: {request.build_absolute_uri(path)}\n\n"
                "O convite é individual, temporário e pode ser usado uma única vez."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[issued.invitation.recipient_email],
        )
        message.send()
        return TemplateResponse(
            request,
            "accounts/auth_message.html",
            {
                "page_title": "Convite enviado",
                "title": "Convite enviado",
                "message": "O convite foi enviado para o endereço informado.",
                "action_url": reverse("invitation_issue"),
                "action_label": "Enviar outro convite",
            },
        )
    return _form_response(
        request,
        form=form,
        title="Convidar pessoa",
        description="Defina o acesso inicial e a validade do convite.",
        submit_label="Enviar convite",
    )


@require_http_methods(["GET", "POST"])
def invitation_accept(request: HttpRequest, raw_token: str) -> HttpResponse:
    """Accept an invitation for a new or already authenticated identity."""
    actor = request.user if isinstance(request.user, User) else None
    if request.method == "POST" and actor is not None:
        clinic_id = invitation_clinic_id(raw_token=raw_token)
        accept_invitation(
            raw_token=raw_token,
            password="",
            first_name="",
            last_name="",
            actor=actor,
        )
        request.session[CLINIC_SESSION_KEY] = str(clinic_id)
        return redirect("workspace_vertical")

    form = InvitationAcceptanceForm(request.POST or None)
    if request.method == "POST":
        if not request.POST:
            return redirect(f"{reverse('account_login')}?next={request.path}")
        if form.is_valid():
            try:
                accept_invitation(
                    raw_token=raw_token,
                    password=form.cleaned_data["password"],
                    first_name=form.cleaned_data["first_name"],
                    last_name=form.cleaned_data["last_name"],
                )
            except PermissionDenied, ValueError, ValidationError:
                form.add_error(None, "Convite inválido ou expirado.")
            else:
                return redirect("account_login")
    return _form_response(
        request,
        form=form,
        title="Aceitar convite",
        description="Confirme seus dados para criar o acesso à clínica.",
        submit_label="Aceitar convite",
    )


@login_required
@require_POST
def invitation_revoke(request: HttpRequest, invitation_id: UUID) -> HttpResponse:
    """Revoke one pending invitation through a POST-only tenant action."""
    actor = request.user
    if not isinstance(actor, User):
        raise PermissionDenied
    revoke_invitation(
        clinic_id=_active_clinic_id(request),
        invitation_id=invitation_id,
        actor=actor,
    )
    return redirect("invitation_issue")


@require_http_methods(["GET", "POST"])
def password_recovery(request: HttpRequest) -> HttpResponse:
    """Accept a recovery request with a generic non-enumerating response."""
    form = PasswordRecoveryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        status = 200
        try:
            request_password_recovery(
                request=request,
                email=form.cleaned_data["email"],
            )
        except RecoveryRateLimitedError:
            status = 429
        response = TemplateResponse(
            request,
            "accounts/auth_message.html",
            {
                "page_title": "Solicitação recebida",
                "title": "Verifique seu e-mail",
                "message": GENERIC_RECOVERY_RESPONSE,
                "action_url": reverse("account_login"),
                "action_label": "Voltar para entrar",
            },
            status=status,
        )
        if status == 429:
            response.headers["Retry-After"] = str(
                max(1, int(settings.PASSWORD_RECOVERY_RATE_LIMIT_WINDOW_SECONDS))
            )
        return response
    return _form_response(
        request,
        form=form,
        title="Recuperar acesso",
        description="Informe seu e-mail para receber instruções de recuperação.",
        submit_label="Enviar instruções",
        secondary_url=reverse("account_login"),
        secondary_label="Voltar para entrar",
    )


@require_http_methods(["GET", "POST"])
def password_reset(request: HttpRequest, uid: str, token: str) -> HttpResponse:
    """Replace a credential through one valid, short-lived reset token."""
    identity = password_reset_identity(uid=uid, token=token)
    if identity is None:
        return TemplateResponse(
            request,
            "accounts/auth_message.html",
            {
                "page_title": "Link inválido",
                "title": "Link inválido ou expirado.",
                "message": "Solicite novas instruções para recuperar seu acesso.",
                "action_url": reverse("password_recovery"),
                "action_label": "Solicitar novo link",
            },
            status=400,
        )
    form = PasswordResetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if reset_password(
            uid=uid,
            token=token,
            new_password=form.cleaned_data["new_password"],
        ):
            return redirect("password_reset_complete")
        return TemplateResponse(
            request,
            "accounts/auth_message.html",
            {
                "page_title": "Link inválido",
                "title": "Link inválido ou expirado.",
                "message": "Solicite novas instruções para recuperar seu acesso.",
                "action_url": reverse("password_recovery"),
                "action_label": "Solicitar novo link",
            },
            status=400,
        )
    return _form_response(
        request,
        form=form,
        title="Definir nova senha",
        description="Escolha uma nova senha para proteger sua conta.",
        submit_label="Salvar nova senha",
    )


def password_reset_complete(request: HttpRequest) -> TemplateResponse:
    """Confirm successful credential replacement without exposing account data."""
    return TemplateResponse(
        request,
        "accounts/auth_message.html",
        {
            "page_title": "Senha alterada",
            "title": "Senha alterada com segurança",
            "message": "Entre novamente em todos os seus dispositivos.",
            "action_url": reverse("account_login"),
            "action_label": "Entrar",
        },
    )


def _authenticated_user(request: HttpRequest) -> User:
    actor = request.user
    if not isinstance(actor, User):
        raise PermissionDenied
    return actor


def _protect_mfa_response(response: HttpResponse) -> HttpResponse:
    """Prevent MFA enrollment material from being cached or indexed."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@sensitive_variables()
def _render_sensitive_mfa_template(
    request: HttpRequest,
    template_name: str,
    context: dict[str, object],
    *,
    status: int = 200,
) -> HttpResponse:
    """Render eagerly and suppress descendant tracebacks with MFA material."""
    try:
        response = TemplateResponse(request, template_name, context, status=status)
        response.render()
    except Exception:
        raise RuntimeError("Unable to render the MFA response.") from None
    return response


@sensitive_variables("secret", "totp_uri")
def _mfa_enrollment_response(
    request: HttpRequest,
    *,
    form: MFACodeForm,
    secret: str,
    status: int = 200,
) -> HttpResponse:
    """Render local TOTP provisioning data without exposing it to third parties."""
    totp_uri = build_totp_key_uri(
        secret=secret,
        issuer=settings.MFA_TOTP_ISSUER,
        account=_authenticated_user(request).email.strip().lower(),
    )
    response = _render_sensitive_mfa_template(
        request,
        "accounts/mfa_enroll.html",
        {
            "page_title": "Ativar autenticação em duas etapas",
            "form": form,
            "manual_secret": secret,
            "totp_uri": totp_uri,
            "qr_data_uri": build_totp_qr_data_uri(uri=totp_uri),
        },
        status=status,
    )
    return _protect_mfa_response(response)


@login_required
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("code")
@sensitive_variables("secret", "recovery_codes")
def mfa_enroll(request: HttpRequest) -> HttpResponse:
    """Enroll and confirm TOTP before privileged access is permitted."""
    actor = _authenticated_user(request)
    mfa = UserMFA.objects.filter(user=actor).first()
    if mfa is not None and mfa.is_confirmed:
        return redirect("mfa_verify")
    secret = (
        start_totp_enrollment(user=actor).secret
        if mfa is None
        else mfa.decrypt_secret()
    )
    if request.method == "POST" and request.POST.get("action") == "restart":
        secret = start_totp_enrollment(user=actor).secret
        return _mfa_enrollment_response(
            request,
            form=MFACodeForm(),
            secret=secret,
        )
    form = MFACodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            recovery_codes = confirm_totp_enrollment(
                user=actor,
                code=form.cleaned_data["code"],
            )
        except MFAAttemptRateLimitedError:
            form.add_error("code", "Muitas tentativas. Tente novamente mais tarde.")
            response = _mfa_enrollment_response(
                request,
                form=form,
                secret=secret,
                status=429,
            )
            response.headers["Retry-After"] = str(
                settings.MFA_RATE_LIMIT_WINDOW_SECONDS
            )
            return _protect_mfa_response(response)
        except ValueError:
            form.add_error("code", "Código inválido ou expirado.")
        else:
            request.session["mfa_verified"] = True
            continue_url = _safe_local_next(
                request,
                request.session.pop("mfa_next", None),
            ) or reverse("workspace_vertical")
            response = _render_sensitive_mfa_template(
                request,
                "accounts/mfa_recovery_codes.html",
                {
                    "page_title": "Códigos de recuperação",
                    "title": "Códigos de recuperação",
                    "description": (
                        "Guarde estes códigos antes de continuar; "
                        "eles não serão exibidos novamente."
                    ),
                    "recovery_codes": recovery_codes,
                    "continue_url": continue_url,
                },
            )
            return _protect_mfa_response(response)
    return _mfa_enrollment_response(
        request,
        form=form,
        secret=secret,
    )


@login_required
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("code")
@sensitive_variables()
def mfa_verify(request: HttpRequest) -> HttpResponse:
    """Verify a fresh TOTP or consume one recovery credential."""
    actor = _authenticated_user(request)
    form = MFACodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            verified = consume_mfa_code(user=actor, code=form.cleaned_data["code"])
        except MFAAttemptRateLimitedError:
            form.add_error("code", "Muitas tentativas. Tente novamente mais tarde.")
            response = _form_response(
                request,
                form=form,
                title="Confirmar autenticação em duas etapas",
                description="Informe o código do aplicativo ou de recuperação.",
                submit_label="Verificar",
                status=429,
            )
            response.headers["Retry-After"] = str(
                settings.MFA_RATE_LIMIT_WINDOW_SECONDS
            )
            return _protect_mfa_response(response)
        except Exception:
            raise RuntimeError("Unable to verify the MFA code.") from None
        if verified:
            request.session["mfa_verified"] = True
            next_url = _safe_local_next(
                request,
                request.session.pop("mfa_next", None),
            )
            if next_url is not None:
                return redirect(next_url)
            return redirect("workspace_vertical")
        form.add_error("code", "Código inválido ou já utilizado.")
    return _protect_mfa_response(
        _form_response(
            request,
            form=form,
            title="Confirmar autenticação em duas etapas",
            description="Informe o código do aplicativo ou um código de recuperação.",
            submit_label="Verificar",
        )
    )


@login_required
@require_http_methods(["GET", "POST"])
def account_sessions(request: HttpRequest) -> HttpResponse:
    """List minimized active devices and process explicit revocation actions."""
    actor = _authenticated_user(request)
    current = getattr(request, "account_session", None)
    reauthentication_form = SensitiveActionReauthenticationForm(
        request.POST if request.method == "POST" else None
    )
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "revoke_others" and isinstance(current, AccountSession):
            try:
                reauthenticated = (
                    reauthentication_form.is_valid()
                    and reauthenticate_sensitive_action(
                        actor=actor,
                        password=reauthentication_form.cleaned_data.get("password", ""),
                    )
                )
            except SensitiveActionRateLimitedError:
                reauthentication_form.add_error(
                    "password", "Muitas tentativas. Tente novamente mais tarde."
                )
                sessions = AccountSession.objects.filter(user=actor).order_by(
                    "-last_seen_at"
                )
                response = TemplateResponse(
                    request,
                    "accounts/sessions.html",
                    {
                        "account_sessions": sessions,
                        "current_session": current,
                        "reauthentication_form": reauthentication_form,
                    },
                    status=429,
                )
                response.headers["Retry-After"] = str(
                    settings.SENSITIVE_REAUTH_RATE_LIMIT_WINDOW_SECONDS
                )
                return response
            if not reauthenticated:
                reauthentication_form.add_error(
                    "password", "Não foi possível confirmar sua senha atual."
                )
                sessions = AccountSession.objects.filter(user=actor).order_by(
                    "-last_seen_at"
                )
                return TemplateResponse(
                    request,
                    "accounts/sessions.html",
                    {
                        "account_sessions": sessions,
                        "current_session": current,
                        "reauthentication_form": reauthentication_form,
                    },
                    status=400,
                )
            revoke_other_sessions(
                actor=actor,
                current_session_id=current.pk,
                clinic_id=_active_clinic_id(request),
            )
        elif action == "revoke":
            try:
                session_id = UUID(str(request.POST.get("session_id")))
            except TypeError, ValueError, AttributeError:
                raise PermissionDenied from None
            revoke_account_session(
                actor=actor,
                account_session_id=session_id,
                clinic_id=_active_clinic_id(request),
            )
        return redirect("account_sessions")
    sessions = AccountSession.objects.filter(user=actor).order_by("-last_seen_at")
    return TemplateResponse(
        request,
        "accounts/sessions.html",
        {
            "account_sessions": sessions,
            "current_session": current,
            "reauthentication_form": reauthentication_form,
        },
    )
