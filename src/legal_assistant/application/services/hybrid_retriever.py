from __future__ import annotations

from dataclasses import replace
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
        graph_fanout_limit: int = 20,
        rrf_k: int = 60,
    ) -> None:
        self._embeddings = embeddings
        self._vector_store = vector_store
        self._graph_store = graph_store
        self._graph_depth = graph_depth
        self._graph_fanout_limit = graph_fanout_limit
        self._rrf_k = rrf_k

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
            [context.chunk_id for context in vector_contexts],
            depth=self._graph_depth,
            limit=self._graph_fanout_limit,
        )
        return self._merge_contexts(vector_contexts, graph_contexts, top_k=top_k)

    def _merge_contexts(
        self,
        vector_contexts: list[RetrievedContext],
        graph_contexts: list[RetrievedContext],
        *,
        top_k: int,
    ) -> list[RetrievedContext]:
        # Vector cosine-similarity scores and graph-expansion scores are not on
        # the same scale, so they must never be sorted together as raw values.
        # Fuse by rank (Reciprocal Rank Fusion) instead: each source list's
        # position, not its score, determines its contribution.
        fused_scores: dict[str, float] = {}
        by_id: dict[str, RetrievedContext] = {}
        for rank, context in enumerate(vector_contexts):
            fused_scores[context.chunk_id] = fused_scores.get(
                context.chunk_id, 0.0
            ) + 1.0 / (self._rrf_k + rank)
            by_id[context.chunk_id] = context
        for rank, context in enumerate(graph_contexts):
            fused_scores[context.chunk_id] = fused_scores.get(
                context.chunk_id, 0.0
            ) + 1.0 / (self._rrf_k + rank)
            by_id.setdefault(context.chunk_id, context)

        ranked_ids = sorted(
            fused_scores, key=lambda chunk_id: fused_scores[chunk_id], reverse=True
        )[:top_k]
        return [
            replace(by_id[chunk_id], score=fused_scores[chunk_id])
            for chunk_id in ranked_ids
        ]
