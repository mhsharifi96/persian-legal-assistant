from __future__ import annotations

from typing import Any

from legal_assistant.application.ports import (
    EmbeddingModelPort,
    GraphRepository,
    HybridRetrieverPort,
    VectorStoreRepository,
)
from legal_assistant.domain.models import RetrievedContext


class HybridRetriever(HybridRetrieverPort):
    def __init__(
        self,
        embeddings: EmbeddingModelPort,
        vector_store: VectorStoreRepository,
        graph_store: GraphRepository,
        *,
        graph_depth: int = 1,
    ) -> None:
        self._embeddings = embeddings
        self._vector_store = vector_store
        self._graph_store = graph_store
        self._graph_depth = graph_depth

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedContext]:
        query_vector = self._embeddings.embed_query(query)
        vector_contexts = self._vector_store.search(
            query_vector, filters=filters, top_k=top_k
        )
        graph_contexts = self._graph_store.expand_context(
            [context.chunk_id for context in vector_contexts], depth=self._graph_depth
        )
        return self._merge_contexts(vector_contexts, graph_contexts, top_k=top_k)

    def _merge_contexts(
        self,
        vector_contexts: list[RetrievedContext],
        graph_contexts: list[RetrievedContext],
        *,
        top_k: int,
    ) -> list[RetrievedContext]:
        merged: dict[str, RetrievedContext] = {}
        for context in vector_contexts + graph_contexts:
            existing = merged.get(context.chunk_id)
            if existing is None or context.score > existing.score:
                merged[context.chunk_id] = context
        return sorted(merged.values(), key=lambda item: item.score, reverse=True)[:top_k]
