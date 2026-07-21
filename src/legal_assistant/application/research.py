from __future__ import annotations

from collections.abc import Sequence

from legal_assistant.application.ports import (
    LegalGraphSearchPort,
    LegalVectorSearchPort,
)
from legal_assistant.domain.research import LegalEvidence


class LegalResearchService:
    """Capped read-side access used by agent tools and deterministic callers."""

    def __init__(
        self,
        vector_search: LegalVectorSearchPort,
        graph_search: LegalGraphSearchPort,
        *,
        max_search_results: int = 8,
        max_graph_depth: int = 2,
        max_graph_results: int = 16,
    ) -> None:
        if max_search_results <= 0:
            raise ValueError("max_search_results must be greater than zero")
        if max_graph_depth <= 0:
            raise ValueError("max_graph_depth must be greater than zero")
        if max_graph_results <= 0:
            raise ValueError("max_graph_results must be greater than zero")
        self._vector_search = vector_search
        self._graph_search = graph_search
        self._max_search_results = max_search_results
        self._max_graph_depth = max_graph_depth
        self._max_graph_results = max_graph_results

    def semantic_search(self, query: str, *, top_k: int = 6) -> list[LegalEvidence]:
        normalized = query.strip()
        if not normalized:
            raise ValueError("query must not be empty")
        safe_top_k = max(1, min(int(top_k), self._max_search_results))
        return self._deduplicate(
            self._vector_search.search(normalized, top_k=safe_top_k)
        )

    def expand_graph(
        self,
        entity_ids: Sequence[str],
        *,
        depth: int = 1,
        limit: int = 12,
    ) -> list[LegalEvidence]:
        normalized_ids = tuple(
            dict.fromkeys(value.strip() for value in entity_ids if value.strip())
        )
        if not normalized_ids:
            return []
        safe_depth = max(1, min(int(depth), self._max_graph_depth))
        safe_limit = max(1, min(int(limit), self._max_graph_results))
        return self._deduplicate(
            self._graph_search.expand(
                normalized_ids,
                depth=safe_depth,
                limit=safe_limit,
            )
        )

    @staticmethod
    def _deduplicate(evidence: Sequence[LegalEvidence]) -> list[LegalEvidence]:
        best: dict[str, LegalEvidence] = {}
        for item in evidence:
            previous = best.get(item.evidence_id)
            if previous is None or item.score > previous.score:
                best[item.evidence_id] = item
        return sorted(best.values(), key=lambda item: item.score, reverse=True)
