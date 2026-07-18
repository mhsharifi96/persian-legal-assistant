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
    DocumentParserPort,
    DocumentStore,
    EmbeddingModelPort,
    EvaluationRepository,
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
    FakeDocumentParser,
    FakeEmbeddingModel,
    InMemoryDocumentStore,
    InMemoryEvaluationRepository,
    InMemoryGraphRepository,
    InMemoryLawyerWriteRepository,
    InMemoryVectorStoreRepository,
    TaggedFakeLLM,
)
from legal_assistant.infrastructure.repositories.jsonl import (
    JsonlEvaluationRepository,
    JsonlLawyerRepository,
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

PARSER_BUILDERS: dict[str, Callable[[Settings], DocumentParserPort]] = {
    "fake": lambda settings: FakeDocumentParser([]),
}


def _openai_embedding_model(settings: Settings) -> EmbeddingModelPort:
    from legal_assistant.infrastructure.embeddings import OpenAIEmbeddingModel

    return OpenAIEmbeddingModel(
        model_name=settings.embedding_model_name,
        dimensions=settings.embedding_dimensions,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )


def _qdrant_vector_store(settings: Settings) -> VectorStoreRepository:
    from legal_assistant.infrastructure.vectorstores import (
        QdrantVectorStoreRepository,
    )

    return QdrantVectorStoreRepository(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection_name,
        api_key=settings.qdrant_api_key,
    )


def _neo4j_graph_store(settings: Settings) -> GraphRepository:
    from legal_assistant.infrastructure.graphstores import Neo4jGraphRepository

    return Neo4jGraphRepository(
        uri=settings.neo4j_uri,
        username=settings.neo4j_username,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
    )


def _openai_llm(settings: Settings) -> LLMPort:
    from legal_assistant.infrastructure.llms import OpenAILLM

    return OpenAILLM(
        model_name=settings.llm_model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )


def _local_document_parser(settings: Settings) -> DocumentParserPort:
    from legal_assistant.infrastructure.parsers import LocalFileDocumentParser

    return LocalFileDocumentParser(jurisdiction=settings.jurisdiction)


EMBEDDING_BUILDERS["openai"] = _openai_embedding_model
VECTORSTORE_BUILDERS["qdrant"] = _qdrant_vector_store
GRAPHSTORE_BUILDERS["neo4j"] = _neo4j_graph_store
LLM_BUILDERS["openai"] = _openai_llm
PARSER_BUILDERS["local"] = _local_document_parser


# --- Admin/API persistence registries ---------------------------------------
# The "orm" builders are imported lazily inside the lambda so that importing
# bootstrap never requires Django to be configured (unit tests, ingestion CLI).


def _orm_lawyer_repository(settings: Settings) -> LawyerRepository:
    from legal_assistant.infrastructure.orm.repositories import OrmLawyerRepository

    return OrmLawyerRepository()


def _orm_document_store(settings: Settings) -> DocumentStore:
    from legal_assistant.infrastructure.orm.repositories import OrmDocumentStore

    return OrmDocumentStore()


def _orm_evaluation_repository(settings: Settings) -> EvaluationRepository:
    from legal_assistant.infrastructure.orm.repositories import OrmEvaluationRepository

    return OrmEvaluationRepository()


LAWYER_REPO_BUILDERS: dict[str, Callable[[Settings], LawyerRepository]] = {
    "memory": lambda settings: InMemoryLawyerWriteRepository(),
    "jsonl": lambda settings: JsonlLawyerRepository(settings.lawyer_data_path),
    "orm": _orm_lawyer_repository,
}

DOCUMENT_STORE_BUILDERS: dict[str, Callable[[Settings], DocumentStore]] = {
    "memory": lambda settings: InMemoryDocumentStore(),
    "orm": _orm_document_store,
}

EVALUATION_REPO_BUILDERS: dict[str, Callable[[Settings], EvaluationRepository]] = {
    "memory": lambda settings: InMemoryEvaluationRepository(),
    "jsonl": lambda settings: JsonlEvaluationRepository(settings.evaluation_data_path),
    "orm": _orm_evaluation_repository,
}


def build_lawyer_repository(settings: Settings) -> LawyerRepository:
    try:
        return LAWYER_REPO_BUILDERS[settings.lawyer_repo_provider](settings)
    except KeyError:
        raise ValueError(
            f"Unsupported lawyer repo provider: {settings.lawyer_repo_provider}"
        )


def build_document_parser(settings: Settings) -> DocumentParserPort:
    try:
        return PARSER_BUILDERS[settings.parser_provider](settings)
    except KeyError:
        raise ValueError(f"Unsupported parser provider: {settings.parser_provider}")


def build_document_store(settings: Settings) -> DocumentStore:
    try:
        return DOCUMENT_STORE_BUILDERS[settings.document_store_provider](settings)
    except KeyError:
        raise ValueError(
            f"Unsupported document store provider: {settings.document_store_provider}"
        )


def build_evaluation_repository(settings: Settings) -> EvaluationRepository:
    try:
        return EVALUATION_REPO_BUILDERS[settings.evaluation_repo_provider](settings)
    except KeyError:
        raise ValueError(
            f"Unsupported evaluation repo provider: {settings.evaluation_repo_provider}"
        )


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
    embeddings = build_embedding_model(settings)
    return HybridRetriever(
        embeddings=embeddings,
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
