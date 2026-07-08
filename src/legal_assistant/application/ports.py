from __future__ import annotations

from typing import Any, Protocol, Sequence

from legal_assistant.domain.models import (
    EvaluationRecord,
    GraphEntity,
    GraphExtraction,
    GraphRelation,
    IngestionErrorRecord,
    LawyerProfile,
    LegalChunk,
    LegalDocument,
    RetrievedContext,
)


class DocumentParserPort(Protocol):
    def parse(self, source_uri: str) -> list[LegalDocument]: ...


class LegalChunkerPort(Protocol):
    def chunk(self, document: LegalDocument) -> list[LegalChunk]: ...


class EmbeddingModelPort(Protocol):
    @property
    def dimension(self) -> int: ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class VectorStoreRepository(Protocol):
    def upsert_chunks(
        self, chunks: Sequence[LegalChunk], vectors: Sequence[list[float]]
    ) -> None: ...

    def search(
        self,
        query_vector: list[float],
        *,
        filters: dict[str, Any] | None,
        top_k: int,
    ) -> list[RetrievedContext]: ...


class GraphRepository(Protocol):
    def upsert_entities(self, entities: Sequence[GraphEntity]) -> None: ...

    def upsert_relations(self, relations: Sequence[GraphRelation]) -> None: ...

    def expand_context(
        self, chunk_ids: Sequence[str], *, depth: int, limit: int | None = None
    ) -> list[RetrievedContext]: ...


class LLMPort(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        response_schema: dict[str, Any] | None = None,
    ) -> str | dict[str, Any]: ...


class GraphExtractorPort(Protocol):
    def extract(self, chunk: LegalChunk) -> GraphExtraction: ...


class HybridRetrieverPort(Protocol):
    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedContext]: ...


class CrewAnalysisPort(Protocol):
    """Optional multi-agent (e.g. CrewAI) debate over complex disputes.

    Wrapped behind an adapter so the core graph works without it. Given the
    user query and the assembled context, it returns supplementary analysis
    text that ``generation_node`` may fold into its answer.
    """

    def analyze(self, query: str, context: Sequence[RetrievedContext]) -> str: ...


class IngestionErrorSink(Protocol):
    def record(self, error: IngestionErrorRecord) -> None: ...


class CheckpointRepository(Protocol):
    def save(self, key: str, value: dict[str, Any]) -> None: ...

    def load(self, key: str) -> dict[str, Any] | None: ...


class LawyerRepository(Protocol):
    def list_lawyers(
        self, *, filters: dict[str, Any] | None = None
    ) -> list[LawyerProfile]: ...


class EvaluationRepository(Protocol):
    def load_records(self) -> list[EvaluationRecord]: ...
