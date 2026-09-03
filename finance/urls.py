"""URL routes for the finance domain."""

from django.urls import path

from .views import (
    charge_cancel,
    charge_generate,
    charge_list,
    charge_settle,
    service_price_create,
)

urlpatterns = [
    path("", charge_list, name="charge_list"),
    path("precos/novo/", service_price_create, name="service_price_create"),
    path(
        "cobrancas/<uuid:appointment_id>/gerar/",
        charge_generate,
        name="charge_generate",
    ),
    path("cobrancas/<uuid:charge_id>/baixar/", charge_settle, name="charge_settle"),
    path("cobrancas/<uuid:charge_id>/cancelar/", charge_cancel, name="charge_cancel"),
]
