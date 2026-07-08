from __future__ import annotations

from django.urls import path

from legal_assistant.interfaces.api import views

app_name = "api"

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("lawyers/", views.LawyerListView.as_view(), name="lawyer-list"),
    path(
        "lawyers/recommend/",
        views.LawyerRecommendView.as_view(),
        name="lawyer-recommend",
    ),
    path(
        "lawyers/<str:lawyer_id>/",
        views.LawyerDetailView.as_view(),
        name="lawyer-detail",
    ),
    path("documents/", views.DocumentListView.as_view(), name="document-list"),
    path("chunks/", views.ChunkListView.as_view(), name="chunk-list"),
    path("evaluations/", views.EvaluationListView.as_view(), name="evaluation-list"),
    path(
        "evaluations/run/",
        views.EvaluationRunView.as_view(),
        name="evaluation-run",
    ),
    path("ask/", views.AskView.as_view(), name="ask"),
]
