from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from legal_assistant.domain.research import AuthorityTier
from legal_assistant.infrastructure.retrieval.qdrant import QdrantLegalVectorSearch


class StubEmbeddings:
    dimension = 3

    def embed_query(self, text: str) -> list[float]:
        assert text == "ماده ده"
        return [0.1, 0.2, 0.3]


@dataclass
class Point:
    id: str
    score: float
    payload: dict[str, Any]


@dataclass
class QueryResponse:
    points: list[Point]


class FakeQdrantClient:
    def __init__(self) -> None:
        self.query: list[float] = []
        self.limit = 0

    def collection_exists(self, name: str) -> bool:
        return name == "legal_graph_nodes"

    def query_points(self, **kwargs: Any) -> QueryResponse:
        self.query = kwargs["query"]
        self.limit = kwargs["limit"]
        return QueryResponse(
            points=[
                Point(
                    id="point-1",
                    score=0.91,
                    payload={
                        "entity_id": "article:10",
                        "labels": ["LegalEntity", "LawNode", "Article"],
                        "title": "ماده ۱۰ قانون مدنی",
                        "text": "قراردادهای خصوصی نسبت به کسانی که آن را منعقد نموده‌اند نافذ است.",
                        "url": "https://example.test/article/10",
                        "node_type": "article",
                        "source_datasets": ["laws"],
                        "chunk_index": 0,
                        "chunk_count": 1,
                    },
                ),
                Point(
                    id="point-2",
                    score=0.6,
                    payload={
                        "entity_id": "answer:1:1",
                        "labels": ["LegalEntity", "DadrahNode", "Answer"],
                        "title": "پاسخ ۱",
                        "text": "یک پاسخ عمومی",
                    },
                ),
            ]
        )


def test_qdrant_search_maps_current_payload_and_authority() -> None:
    client = FakeQdrantClient()
    search = QdrantLegalVectorSearch(
        StubEmbeddings(),
        url="http://unused",
        collection_name="legal_graph_nodes",
        client=client,
    )

    results = search.search("ماده ده", top_k=5)

    assert client.query == [0.1, 0.2, 0.3]
    assert client.limit == 5
    assert results[0].evidence_id == "qdrant:point-1"
    assert results[0].entity_id == "article:10"
    assert results[0].authority is AuthorityTier.PRIMARY
    assert results[1].authority is AuthorityTier.AUXILIARY
