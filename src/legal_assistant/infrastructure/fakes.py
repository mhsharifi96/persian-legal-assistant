from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Sequence

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


class FakeDocumentParser:
    def __init__(self, documents: Sequence[LegalDocument]) -> None:
        self._documents = list(documents)

    def parse(self, source_uri: str) -> list[LegalDocument]:
        return [document for document in self._documents if document.source_uri == source_uri]


class FakeEmbeddingModel:
    def __init__(self, dimension: int = 8) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for index, char in enumerate(text):
            vector[index % self._dimension] += (ord(char) % 31) / 31
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class FailingBatchEmbeddingModel(FakeEmbeddingModel):
    """Fails embed_texts for any batch containing a poisoned text, but still
    embeds individual items via embed_query unless they are poisoned."""

    def __init__(self, poison_texts: Sequence[str], dimension: int = 8) -> None:
        super().__init__(dimension)
        self._poison_texts = set(poison_texts)

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if any(text in self._poison_texts for text in texts):
            raise RuntimeError("embedding provider batch failure")
        return super().embed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        if text in self._poison_texts:
            raise RuntimeError("embedding provider item failure")
        return super().embed_query(text)


class InMemoryVectorStoreRepository:
    def __init__(self) -> None:
        self.chunks: dict[str, LegalChunk] = {}
        self.vectors: dict[str, list[float]] = {}

    def upsert_chunks(
        self, chunks: Sequence[LegalChunk], vectors: Sequence[list[float]]
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        for chunk, vector in zip(chunks, vectors, strict=True):
            self.chunks[chunk.id] = chunk
            self.vectors[chunk.id] = vector

    def search(
        self,
        query_vector: list[float],
        *,
        filters: dict[str, Any] | None,
        top_k: int,
    ) -> list[RetrievedContext]:
        contexts: list[RetrievedContext] = []
        for chunk_id, chunk in self.chunks.items():
            if filters and any(chunk.metadata.get(key) != value for key, value in filters.items()):
                continue
            score = cosine_similarity(query_vector, self.vectors[chunk_id])
            contexts.append(
                RetrievedContext(
                    chunk_id=chunk.id,
                    text=chunk.text,
                    score=score,
                    source="vector",
                    hierarchy=chunk.hierarchy,
                    citations=chunk.citations,
                    metadata=chunk.metadata,
                )
            )
        return sorted(contexts, key=lambda item: item.score, reverse=True)[:top_k]


class InMemoryGraphRepository:
    def __init__(self) -> None:
        self.entities: dict[str, GraphEntity] = {}
        self.relations: list[GraphRelation] = []
        self.contexts_by_chunk_id: dict[str, list[RetrievedContext]] = defaultdict(list)
        self.chunks: dict[str, LegalChunk] = {}
        self.entity_ids_by_chunk: dict[str, set[str]] = defaultdict(set)

    def upsert_entities(self, entities: Sequence[GraphEntity]) -> None:
        for entity in entities:
            self.entities[entity.id] = entity

    def upsert_relations(self, relations: Sequence[GraphRelation]) -> None:
        self.relations.extend(relations)

    def link_chunk(self, chunk: LegalChunk, entity_ids: Sequence[str]) -> None:
        self.chunks[chunk.id] = chunk
        self.entity_ids_by_chunk[chunk.id].update(entity_ids)

    def expand_context(
        self, chunk_ids: Sequence[str], *, depth: int, limit: int | None = None
    ) -> list[RetrievedContext]:
        contexts: list[RetrievedContext] = []
        for chunk_id in chunk_ids:
            neighbors = self.contexts_by_chunk_id.get(chunk_id, [])
            contexts.extend(neighbors[:limit] if limit is not None else neighbors)
            related_entity_ids = self._related_entity_ids(
                self.entity_ids_by_chunk.get(chunk_id, set()), depth
            )
            for neighbor_chunk_id, entity_ids in self.entity_ids_by_chunk.items():
                if neighbor_chunk_id == chunk_id or not related_entity_ids.intersection(
                    entity_ids
                ):
                    continue
                chunk = self.chunks[neighbor_chunk_id]
                contexts.append(
                    RetrievedContext(
                        chunk_id=chunk.id,
                        text=chunk.text,
                        score=1.0,
                        source="graph",
                        hierarchy=chunk.hierarchy,
                        citations=chunk.citations,
                        graph_neighbors=tuple(sorted(related_entity_ids.intersection(entity_ids))),
                        metadata=chunk.metadata,
                    )
                )
        deduplicated = list({context.chunk_id: context for context in contexts}.values())
        return deduplicated[:limit] if limit is not None else deduplicated

    def _related_entity_ids(self, seed_ids: set[str], depth: int) -> set[str]:
        visited = set(seed_ids)
        frontier = set(seed_ids)
        for _ in range(max(0, depth)):
            next_frontier: set[str] = set()
            for relation in self.relations:
                if relation.source_id in frontier:
                    next_frontier.add(relation.target_id)
                if relation.target_id in frontier:
                    next_frontier.add(relation.source_id)
            next_frontier.difference_update(visited)
            visited.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break
        return visited

    def add_context_neighbor(self, chunk_id: str, context: RetrievedContext) -> None:
        self.contexts_by_chunk_id[chunk_id].append(context)


class FakeGraphExtractor:
    def __init__(self, extraction: GraphExtraction | None = None) -> None:
        self.extraction = extraction or GraphExtraction()
        self.seen_chunk_ids: list[str] = []

    def extract(self, chunk: LegalChunk) -> GraphExtraction:
        self.seen_chunk_ids.append(chunk.id)
        return self.extraction


class InMemoryIngestionErrorSink:
    def __init__(self) -> None:
        self.errors: list[IngestionErrorRecord] = []

    def record(self, error: IngestionErrorRecord) -> None:
        self.errors.append(error)


class FakeLLM:
    def __init__(self, responses: Sequence[str | dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.messages: list[list[dict[str, Any]]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        response_schema: dict[str, Any] | None = None,
    ) -> str | dict[str, Any]:
        self.messages.append(messages)
        if not self._responses:
            return {"entities": [], "relationships": []}
        return self._responses.pop(0)


class TaggedFakeLLM:
    """Fake ``LLMPort`` for the agentic core.

    Answers per node using the ``TASK=<tag>`` marker on the first line of the
    system message, so responses are order-independent (retries reuse the same
    tag). ``scripts`` supplies per-tag queues of responses; when a tag's queue
    is empty it falls back to a sensible structured default, which keeps wired
    smoke runs working without a real LLM.
    """

    def __init__(
        self, scripts: dict[str, list[str | dict[str, Any]]] | None = None
    ) -> None:
        self._scripts = {tag: list(queue) for tag, queue in (scripts or {}).items()}
        self.messages: list[list[dict[str, Any]]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        response_schema: dict[str, Any] | None = None,
    ) -> str | dict[str, Any]:
        self.messages.append(messages)
        tag = self._tag(messages)
        queue = self._scripts.get(tag)
        if queue:
            return queue.pop(0)
        return self._default(tag, messages)

    @staticmethod
    def _tag(messages: Sequence[dict[str, Any]]) -> str:
        for message in messages:
            if message.get("role") == "system":
                first_line = str(message.get("content", "")).splitlines()[:1]
                if first_line and first_line[0].startswith("TASK="):
                    return first_line[0].split("=", 1)[1].strip()
        return ""

    @staticmethod
    def _last_user(messages: Sequence[dict[str, Any]]) -> str:
        for message in reversed(list(messages)):
            if message.get("role") == "user":
                return str(message.get("content", ""))
        return ""

    def _default(self, tag: str, messages: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if tag == "router":
            return {"intent": "legal_advice", "confidence": 0.9, "reason": "default"}
        if tag == "decompose":
            return {"queries": [self._last_user(messages)]}
        if tag == "judge":
            return {"is_valid": True, "feedback": [], "next_action": "finalize"}
        if tag == "generate":
            return {
                "summary": "پاسخ بر اساس منابع بازیابی‌شده تنظیم شده است.",
                "analysis": "تحلیل بر پایه مواد قانونی مرتبط ارائه شده است.",
                "cited_chunk_ids": [],
            }
        if tag.startswith("eval_"):
            return {"score": 1.0, "reason": "default"}
        return {}


class FakeCrewAnalysis:
    def __init__(self, analysis: str = "تحلیل تکمیلی گروه کارشناسی.") -> None:
        self._analysis = analysis
        self.calls: list[str] = []

    def analyze(self, query: str, context: Sequence[RetrievedContext]) -> str:
        self.calls.append(query)
        return self._analysis


class InMemoryLawyerRepository:
    """Mock lawyer data source. Swapping in a SQL/API/Pandas-backed repository
    that satisfies ``LawyerRepository`` must not change the service."""

    def __init__(self, profiles: Sequence[LawyerProfile]) -> None:
        self._profiles = list(profiles)

    def list_lawyers(
        self, *, filters: dict[str, Any] | None = None
    ) -> list[LawyerProfile]:
        if not filters:
            return list(self._profiles)
        return [p for p in self._profiles if self._matches(p, filters)]

    @staticmethod
    def _matches(profile: LawyerProfile, filters: dict[str, Any]) -> bool:
        for key, value in filters.items():
            if key == "specialty":
                if value not in profile.specialties:
                    return False
            elif key == "location":
                if profile.location != value:
                    return False
            elif profile.metadata.get(key) != value:
                return False
        return True


class InMemoryEvaluationRepository:
    def __init__(self, records: Sequence[EvaluationRecord] = ()) -> None:
        self._records = list(records)

    def load_records(self) -> list[EvaluationRecord]:
        return list(self._records)

    def append_record(self, record: EvaluationRecord) -> None:
        self._records.append(record)


class InMemoryDocumentStore:
    """In-memory ``DocumentStore`` for tests and the default (empty) profile."""

    def __init__(self) -> None:
        self._documents: dict[str, LegalDocument] = {}
        self._chunks: dict[str, LegalChunk] = {}

    def save_document(
        self, document: LegalDocument, chunks: Sequence[LegalChunk]
    ) -> None:
        self._documents[document.id] = document
        for chunk in chunks:
            self._chunks[chunk.id] = chunk

    def list_documents(
        self, *, filters: dict[str, Any] | None = None
    ) -> list[LegalDocument]:
        documents = list(self._documents.values())
        if not filters:
            return documents
        return [
            doc
            for doc in documents
            if all(getattr(doc, k, doc.metadata.get(k)) == v for k, v in filters.items())
        ]

    def list_chunks(
        self,
        *,
        document_id: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[LegalChunk]:
        chunks = list(self._chunks.values())
        if document_id is not None:
            chunks = [chunk for chunk in chunks if chunk.document_id == document_id]
        if filters:
            chunks = [
                chunk
                for chunk in chunks
                if all(chunk.metadata.get(k) == v for k, v in filters.items())
            ]
        return chunks


class InMemoryLawyerWriteRepository(InMemoryLawyerRepository):
    """Read+write in-memory lawyer repository for tests."""

    def __init__(self, profiles: Sequence[LawyerProfile] = ()) -> None:
        super().__init__(profiles)

    def get_lawyer(self, lawyer_id: str) -> LawyerProfile | None:
        for profile in self._profiles:
            if profile.lawyer_id == lawyer_id:
                return profile
        return None

    def upsert_lawyer(self, lawyer: LawyerProfile) -> LawyerProfile:
        for index, profile in enumerate(self._profiles):
            if profile.lawyer_id == lawyer.lawyer_id:
                self._profiles[index] = lawyer
                return lawyer
        self._profiles.append(lawyer)
        return lawyer

    def delete_lawyer(self, lawyer_id: str) -> bool:
        for index, profile in enumerate(self._profiles):
            if profile.lawyer_id == lawyer_id:
                del self._profiles[index]
                return True
        return False


class InMemoryCheckpointRepository:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}

    def save(self, key: str, value: dict[str, Any]) -> None:
        self.store[key] = value

    def load(self, key: str) -> dict[str, Any] | None:
        return self.store.get(key)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(y * y for y in right))
    if denominator == 0:
        return 0.0
    return sum(x * y for x, y in zip(left, right, strict=False)) / denominator
