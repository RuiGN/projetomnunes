"""Project URL configuration."""

from django.contrib import admin
from django.urls import include, path

from .views import (
    admin_login_redirect,
    confirm_clinic_switch,
    design_system_reference,
    home,
    liveness,
    readiness,
    review_clinic_switch,
    save_workspace_layout,
    workspace_detached,
    workspace_vertical,
)

handler400 = "config.views.bad_request"
handler403 = "config.views.permission_denied"
handler404 = "config.views.page_not_found"
handler500 = "config.views.server_error"

urlpatterns = [
    path("", home, name="home"),
    path("accounts/", include("accounts.urls")),
    path("clinics/", include("clinics.urls")),
    path("people/", include("people.urls")),
    path("consents/", include("consents.urls")),
    path("journal/", include("journal.urls")),
    path("goals/", include("goals.urls")),
    path("agenda/", include("scheduling.urls")),
    path("analytics/", include("analytics.urls")),
    path("financeiro/", include("finance.urls")),
    path("onboarding/", include("onboarding.urls")),
    path("conteudos/", include("content.urls")),
    path("dashboard/", include("therapist_dashboard.urls")),
    path("design-system/", design_system_reference, name="design_system_reference"),
    path("workspace/", workspace_vertical, name="workspace_vertical"),
    path("workspace/detached/", workspace_detached, name="workspace_detached"),
    path(
        "workspace/preferences/layout/",
        save_workspace_layout,
        name="workspace_layout_preference",
    ),
    path("clinics/switch/review/", review_clinic_switch, name="clinic_switch_review"),
    path(
        "clinics/switch/confirm/", confirm_clinic_switch, name="clinic_switch_confirm"
    ),
    path("health/live/", liveness, name="health-live"),
    path("health/ready/", readiness, name="health-ready"),
    path(
        "admin/login/",
        admin_login_redirect,
        name="admin_login",
    ),
    path("admin/", admin.site.urls),
]
