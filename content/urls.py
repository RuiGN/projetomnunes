"""URL routes for the editorial content and curation domains."""

from django.urls import include, path

from .views import (
    content_detail,
    content_publish,
    content_recommend,
    content_report_resolve,
    content_reports,
    editorial_approve,
    editorial_archive,
    editorial_comment,
    editorial_compare,
    editorial_create,
    editorial_detail,
    editorial_index,
    editorial_media,
    editorial_metadata_update,
    editorial_preview,
    editorial_rollback,
    editorial_submit,
    editorial_version_create,
    library_home,
    notification_list,
    recommendation_list,
)

urlpatterns = [
    path("", library_home, name="content_library"),
    path("editorial/", editorial_index, name="content_editorial_index"),
    path("editorial/novo/", editorial_create, name="content_editorial_create"),
    path(
        "editorial/<uuid:content_id>/",
        editorial_detail,
        name="content_editorial_detail",
    ),
    path(
        "editorial/<uuid:content_id>/versoes/nova/",
        editorial_version_create,
        name="content_editorial_version",
    ),
    path(
        "editorial/<uuid:content_id>/versoes/<int:version>/preview/",
        editorial_preview,
        name="content_editorial_preview",
    ),
    path(
        "editorial/<uuid:content_id>/versoes/<int:version>/comentarios/",
        editorial_comment,
        name="content_editorial_comment",
    ),
    path(
        "editorial/<uuid:content_id>/comparar/",
        editorial_compare,
        name="content_editorial_compare",
    ),
    path(
        "editorial/<uuid:content_id>/submeter/",
        editorial_submit,
        name="content_editorial_submit",
    ),
    path(
        "editorial/<uuid:content_id>/aprovar/",
        editorial_approve,
        name="content_editorial_approve",
    ),
    path(
        "editorial/<uuid:content_id>/reverter/",
        editorial_rollback,
        name="content_editorial_rollback",
    ),
    path(
        "editorial/<uuid:content_id>/arquivar/",
        editorial_archive,
        name="content_editorial_archive",
    ),
    path(
        "editorial/<uuid:content_id>/midia/",
        editorial_media,
        name="content_editorial_media",
    ),
    path(
        "editorial/<uuid:content_id>/metadados/",
        editorial_metadata_update,
        name="content_editorial_metadata",
    ),
    path(
        "minhas-recomendacoes/",
        recommendation_list,
        name="content_recommendations",
    ),
    path(
        "notificacoes/",
        notification_list,
        name="content_notifications",
    ),
    path(
        "denuncias/",
        content_reports,
        name="content_reports",
    ),
    path(
        "denuncias/<uuid:report_id>/resolver/",
        content_report_resolve,
        name="content_report_resolve",
    ),
    path(
        "<uuid:content_id>/publicar/",
        content_publish,
        name="content_publish",
    ),
    path(
        "<uuid:content_id>/recomendar/",
        content_recommend,
        name="content_recommend",
    ),
    path("cursos/", include("content.learning_urls")),
    path("<slug:slug>/", content_detail, name="content_detail"),
]
