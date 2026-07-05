from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Sequence

from legal_assistant.domain.models import (
    GraphEntity,
    GraphExtraction,
    GraphRelation,
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

    def upsert_entities(self, entities: Sequence[GraphEntity]) -> None:
        for entity in entities:
            self.entities[entity.id] = entity

    def upsert_relations(self, relations: Sequence[GraphRelation]) -> None:
        self.relations.extend(relations)

    def expand_context(
        self, chunk_ids: Sequence[str], *, depth: int
    ) -> list[RetrievedContext]:
        contexts: list[RetrievedContext] = []
        for chunk_id in chunk_ids:
            contexts.extend(self.contexts_by_chunk_id.get(chunk_id, []))
        return contexts

    def add_context_neighbor(self, chunk_id: str, context: RetrievedContext) -> None:
        self.contexts_by_chunk_id[chunk_id].append(context)


class FakeGraphExtractor:
    def __init__(self, extraction: GraphExtraction | None = None) -> None:
        self.extraction = extraction or GraphExtraction()
        self.seen_chunk_ids: list[str] = []

    def extract(self, chunk: LegalChunk) -> GraphExtraction:
        self.seen_chunk_ids.append(chunk.id)
        return self.extraction


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


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(y * y for y in right))
    if denominator == 0:
        return 0.0
    return sum(x * y for x, y in zip(left, right, strict=False)) / denominator
