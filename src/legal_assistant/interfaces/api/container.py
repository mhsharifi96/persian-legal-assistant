"""Dependency wiring for the API layer.

Reads the single typed ``Settings`` built in Django settings and constructs the
application services/adapters via ``config.bootstrap``. Services are stateless
and cached for the process; provider choices remain env-driven.
"""
from __future__ import annotations

from functools import lru_cache

from django.conf import settings as dj_settings

from legal_assistant.application.agentic.graph import LegalQAGraph
from legal_assistant.application.evaluation.service import EvaluationService
from legal_assistant.application.ports import (
    DocumentStore,
    EvaluationRepository,
    LawyerRepository,
)
from legal_assistant.application.services.lawyer_recommendation import (
    LawyerRecommendationService,
)
from legal_assistant.config import bootstrap
from legal_assistant.config.settings import Settings


def settings() -> Settings:
    return dj_settings.LEGAL_ASSISTANT_SETTINGS


@lru_cache(maxsize=1)
def lawyer_repository() -> LawyerRepository:
    return bootstrap.build_lawyer_repository(settings())


@lru_cache(maxsize=1)
def recommendation_service() -> LawyerRecommendationService:
    return bootstrap.build_lawyer_recommendation_service(
        settings(), lawyer_repository()
    )


@lru_cache(maxsize=1)
def document_store() -> DocumentStore:
    return bootstrap.build_document_store(settings())


@lru_cache(maxsize=1)
def evaluation_repository() -> EvaluationRepository:
    return bootstrap.build_evaluation_repository(settings())


@lru_cache(maxsize=1)
def evaluation_service() -> EvaluationService:
    return bootstrap.build_evaluation_service(settings())


@lru_cache(maxsize=1)
def agentic_graph() -> LegalQAGraph:
    return bootstrap.build_agentic_graph(settings())
