from __future__ import annotations

from typing import Callable

from legal_assistant.application.agentic.components import (
    LLMIntentRouter,
    LLMLegalJudge,
    LLMQueryDecomposer,
    PersianAnswerGenerator,
)
from legal_assistant.application.agentic.graph import LegalQAGraph
from legal_assistant.application.evaluation.metrics import LegalAnswerEvaluator
from legal_assistant.application.evaluation.service import EvaluationService
from legal_assistant.application.ports import (
    EmbeddingModelPort,
    GraphRepository,
    LawyerRepository,
    LLMPort,
    VectorStoreRepository,
)
from legal_assistant.application.services.hybrid_retriever import HybridRetriever
from legal_assistant.application.services.lawyer_recommendation import (
    LawyerRecommendationService,
    RecommendationSettings,
)
from legal_assistant.config.settings import Settings
from legal_assistant.infrastructure.fakes import (
    FakeEmbeddingModel,
    InMemoryGraphRepository,
    InMemoryVectorStoreRepository,
    TaggedFakeLLM,
)

# Provider registries: adding a real adapter is a new dict entry here, not a
# new branch in the builder functions below.
EMBEDDING_BUILDERS: dict[str, Callable[[Settings], EmbeddingModelPort]] = {
    "fake": lambda settings: FakeEmbeddingModel(),
}

VECTORSTORE_BUILDERS: dict[str, Callable[[Settings], VectorStoreRepository]] = {
    "memory": lambda settings: InMemoryVectorStoreRepository(),
}

GRAPHSTORE_BUILDERS: dict[str, Callable[[Settings], GraphRepository]] = {
    "memory": lambda settings: InMemoryGraphRepository(),
}

LLM_BUILDERS: dict[str, Callable[[Settings], LLMPort]] = {
    "fake": lambda settings: TaggedFakeLLM(),
}


def build_embedding_model(settings: Settings) -> EmbeddingModelPort:
    try:
        return EMBEDDING_BUILDERS[settings.embedding_provider](settings)
    except KeyError:
        raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")


def build_vector_store(settings: Settings) -> VectorStoreRepository:
    try:
        return VECTORSTORE_BUILDERS[settings.vectorstore_provider](settings)
    except KeyError:
        raise ValueError(
            f"Unsupported vector store provider: {settings.vectorstore_provider}"
        )


def build_graph_store(settings: Settings) -> GraphRepository:
    try:
        return GRAPHSTORE_BUILDERS[settings.graphstore_provider](settings)
    except KeyError:
        raise ValueError(
            f"Unsupported graph store provider: {settings.graphstore_provider}"
        )


def build_llm(settings: Settings) -> LLMPort:
    try:
        return LLM_BUILDERS[settings.llm_provider](settings)
    except KeyError:
        raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")


def build_hybrid_retriever(settings: Settings) -> HybridRetriever:
    return HybridRetriever(
        embeddings=build_embedding_model(settings),
        vector_store=build_vector_store(settings),
        graph_store=build_graph_store(settings),
        graph_depth=settings.graph_depth,
        graph_fanout_limit=settings.graph_fanout_limit,
        rrf_k=settings.rrf_k,
    )


def build_agentic_graph(
    settings: Settings,
    *,
    retriever: HybridRetriever | None = None,
    llm: LLMPort | None = None,
) -> LegalQAGraph:
    """Wire the Phase 2 reasoning graph from settings. ``retriever`` and ``llm``
    may be injected (e.g. to share a warmed retriever) or built from settings."""
    resolved_llm = llm if llm is not None else build_llm(settings)
    resolved_retriever = (
        retriever if retriever is not None else build_hybrid_retriever(settings)
    )
    return LegalQAGraph(
        router=LLMIntentRouter(resolved_llm),
        decomposer=LLMQueryDecomposer(resolved_llm),
        judge=LLMLegalJudge(resolved_llm),
        generator=PersianAnswerGenerator(resolved_llm),
        retriever=resolved_retriever,
        max_retries=settings.agent_max_retries,
        retrieval_top_k=settings.agent_retrieval_top_k,
        max_context_tokens=settings.agent_max_context_tokens,
        retrieval_max_workers=settings.agent_retrieval_max_workers,
    )


def build_recommendation_settings(settings: Settings) -> RecommendationSettings:
    return RecommendationSettings(
        semantic_weight=settings.rec_semantic_weight,
        success_weight=settings.rec_success_weight,
        location_weight=settings.rec_location_weight,
        top_n=settings.rec_top_n,
    )


def build_lawyer_recommendation_service(
    settings: Settings,
    lawyers: LawyerRepository,
    *,
    embeddings: EmbeddingModelPort | None = None,
) -> LawyerRecommendationService:
    """Wire the recommender. ``lawyers`` (the data source) is injected so the
    repository stays a configuration/adapter choice."""
    return LawyerRecommendationService(
        lawyers=lawyers,
        embeddings=embeddings if embeddings is not None else build_embedding_model(settings),
        settings=build_recommendation_settings(settings),
    )


def build_evaluation_service(
    settings: Settings, *, llm: LLMPort | None = None
) -> EvaluationService:
    resolved_llm = llm if llm is not None else build_llm(settings)
    return EvaluationService(
        LegalAnswerEvaluator(resolved_llm),
        failure_threshold=settings.eval_failure_threshold,
    )
