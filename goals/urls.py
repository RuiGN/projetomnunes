"""URL routes for the goals and exercises domain."""

from django.urls import path

from .exercise_views import (
    exercise_assign_view,
    exercise_catalog,
    exercise_execution_detail_view,
    exercise_form,
    patient_confirm_assignment_view,
    patient_exercise_execute_view,
    patient_exercise_list,
)
from .low_energy_views import (
    low_energy_activate,
    low_energy_configure,
    low_energy_deactivate,
    low_energy_home,
)
from .views import (
    goal_create,
    goal_detail,
    goal_edit,
    goal_list,
    goal_status_change,
    goal_step_toggle,
    goal_visibility_change,
)

urlpatterns = [
    # Goals (8.7.1 & 8.7.2)
    path("", goal_list, name="goal_list"),
    path("nova/", goal_create, name="goal_create"),
    path("<uuid:goal_id>/", goal_detail, name="goal_detail"),
    path("<uuid:goal_id>/editar/", goal_edit, name="goal_edit"),
    path(
        "etapas/<uuid:step_id>/alternar/",
        goal_step_toggle,
        name="goal_step_toggle",
    ),
    path("<uuid:goal_id>/estado/", goal_status_change, name="goal_status_change"),
    path(
        "<uuid:goal_id>/visibilidade/",
        goal_visibility_change,
        name="goal_visibility_change",
    ),
    # Low Energy Mode (8.7.3)
    path("baixa-energia/", low_energy_home, name="low_energy_home"),
    path(
        "baixa-energia/configurar/", low_energy_configure, name="low_energy_configure"
    ),
    path("baixa-energia/ativar/", low_energy_activate, name="low_energy_activate"),
    path(
        "baixa-energia/encerrar/", low_energy_deactivate, name="low_energy_deactivate"
    ),
    # Exercises Catalog & Execution (8.7.4 & 8.7.5)
    path("exercicios/catalogo/", exercise_catalog, name="exercise_catalog"),
    path("exercicios/catalogo/novo/", exercise_form, name="exercise_create"),
    path(
        "exercicios/catalogo/<uuid:exercise_id>/editar/",
        exercise_form,
        name="exercise_edit",
    ),
    path(
        "exercicios/catalogo/<uuid:exercise_id>/atribuir/",
        exercise_assign_view,
        name="exercise_assign",
    ),
    path("exercicios/meus/", patient_exercise_list, name="patient_exercise_list"),
    path(
        "exercicios/atribuicoes/<uuid:assignment_id>/confirmar/",
        patient_confirm_assignment_view,
        name="patient_confirm_assignment",
    ),
    path(
        "exercicios/atribuicoes/<uuid:assignment_id>/executar/",
        patient_exercise_execute_view,
        name="patient_exercise_execute",
    ),
    path(
        "exercicios/execucoes/<uuid:execution_id>/",
        exercise_execution_detail_view,
        name="exercise_execution_detail",
    ),
]
