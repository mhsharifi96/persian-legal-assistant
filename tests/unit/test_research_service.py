from __future__ import annotations

from collections.abc import Sequence

from legal_assistant.application.research import LegalResearchService
from legal_assistant.domain.research import AuthorityTier, LegalEvidence


def _evidence(evidence_id: str, score: float) -> LegalEvidence:
    return LegalEvidence(
        evidence_id=evidence_id,
        entity_id=evidence_id,
        title=evidence_id,
        text="متن",
        source_type="Article",
        authority=AuthorityTier.PRIMARY,
        score=score,
    )


class StubVectorSearch:
    def __init__(self) -> None:
        self.top_k = 0

    def search(self, query: str, *, top_k: int) -> list[LegalEvidence]:
        self.top_k = top_k
        return [_evidence("same", 0.2), _evidence("same", 0.9), _evidence("other", 0.5)]


class StubGraphSearch:
    def __init__(self) -> None:
        self.entity_ids: tuple[str, ...] = ()
        self.depth = 0
        self.limit = 0

    def expand(
        self,
        entity_ids: Sequence[str],
        *,
        depth: int,
        limit: int,
    ) -> list[LegalEvidence]:
        self.entity_ids = tuple(entity_ids)
        self.depth = depth
        self.limit = limit
        return [_evidence("graph", 0.5)]


def test_research_service_caps_and_deduplicates_search() -> None:
    vector = StubVectorSearch()
    service = LegalResearchService(vector, StubGraphSearch(), max_search_results=3)

    results = service.semantic_search("قانون مدنی", top_k=99)

    assert vector.top_k == 3
    assert [(item.evidence_id, item.score) for item in results] == [
        ("same", 0.9),
        ("other", 0.5),
    ]


def test_research_service_only_passes_capped_unique_graph_ids() -> None:
    graph = StubGraphSearch()
    service = LegalResearchService(
        StubVectorSearch(),
        graph,
        max_graph_depth=2,
        max_graph_results=4,
    )

    service.expand_graph([" article:1 ", "article:1", "law:2"], depth=9, limit=99)

    assert graph.entity_ids == ("article:1", "law:2")
    assert graph.depth == 2
    assert graph.limit == 4
