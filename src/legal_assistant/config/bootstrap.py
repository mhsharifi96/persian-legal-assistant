from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Callable, cast

from legal_assistant.application.agent import LegalAgentService
from legal_assistant.application.ports import EmbeddingModelPort
from legal_assistant.application.research import LegalResearchService
from legal_assistant.config.settings import AgentSettings
from legal_assistant.infrastructure.agents import DeepAgentRuntime
from legal_assistant.infrastructure.documents.embeddings import (
    HashingEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from legal_assistant.infrastructure.retrieval import (
    Neo4jLegalGraphSearch,
    QdrantLegalVectorSearch,
)


@dataclass
class AgentContainer:
    """Owns the agent use case and the external clients it must close."""

    agent: LegalAgentService
    _closers: tuple[Callable[[], None], ...]
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: Exception | None = None
        for closer in reversed(self._closers):
            try:
                closer()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def __enter__(self) -> AgentContainer:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def build_agent_container(settings: AgentSettings | None = None) -> AgentContainer:
    resolved = settings or AgentSettings.from_env()
    with ExitStack() as cleanup:
        embeddings = _build_embeddings(resolved)
        closers: list[Callable[[], None]] = []
        embedding_close = getattr(embeddings, "close", None)
        if callable(embedding_close):
            typed_embedding_close = cast(Callable[[], None], embedding_close)
            cleanup.callback(typed_embedding_close)
            closers.append(typed_embedding_close)
        model = _build_chat_model(resolved)
        vector_search = QdrantLegalVectorSearch(
            embeddings,
            url=resolved.qdrant_url,
            collection_name=resolved.qdrant_collection_name,
            api_key=resolved.qdrant_api_key,
        )
        cleanup.callback(vector_search.close)
        closers.append(vector_search.close)
        graph_search = Neo4jLegalGraphSearch(
            uri=resolved.neo4j_uri,
            username=resolved.neo4j_username,
            password=resolved.neo4j_password,
            database=resolved.neo4j_database,
        )
        cleanup.callback(graph_search.close)
        closers.append(graph_search.close)
        research = LegalResearchService(
            vector_search,
            graph_search,
            max_search_results=resolved.max_search_results,
            max_graph_depth=resolved.max_graph_depth,
            max_graph_results=resolved.max_graph_results,
        )
        runtime = DeepAgentRuntime(
            research,
            model=model,
            profile_key=f"{resolved.model_provider}:{resolved.model_name}",
            max_tool_calls=resolved.max_tool_calls,
            recursion_limit=resolved.recursion_limit,
            max_evidence_chars=resolved.max_evidence_chars,
        )
        cleanup.pop_all()
    return AgentContainer(
        agent=LegalAgentService(
            runtime,
            max_question_chars=resolved.max_question_chars,
            max_history_messages=resolved.max_history_messages,
        ),
        _closers=tuple(closers),
    )


def _build_embeddings(settings: AgentSettings) -> EmbeddingModelPort:
    if settings.embedding_provider == "hashing":
        return HashingEmbeddingProvider(dimension=settings.embedding_dimensions)
    if settings.embedding_provider == "openai":
        return OpenAIEmbeddingProvider(
            model_name=settings.embedding_model_name,
            dimension=settings.embedding_dimensions,
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base or None,
            batch_size=settings.embedding_batch_size,
        )
    raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {settings.embedding_provider}")


def _build_chat_model(settings: AgentSettings) -> object:
    if settings.model_provider != "openai":
        raise ValueError(f"Unsupported AGENT_MODEL_PROVIDER: {settings.model_provider}")
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required to build the legal agent")
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base or None,
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
        use_responses_api=settings.openai_use_responses_api,
    )
