from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from legal_assistant.domain.research import AuthorityTier
from legal_assistant.infrastructure.retrieval.neo4j import Neo4jLegalGraphSearch


@dataclass
class FakeResult:
    records: list[dict[str, Any]]


class FakeDriver:
    def __init__(self) -> None:
        self.query: object | None = None
        self.parameters: dict[str, Any] = {}

    def execute_query(self, query: object, **kwargs: Any) -> FakeResult:
        self.query = query
        self.parameters = kwargs
        return FakeResult(
            records=[
                {
                    "entity_id": "unanimity_decision:224",
                    "labels": ["LegalEntity", "UnanimityDecision"],
                    "title": "رأی وحدت رویه شماره ۲۲۴",
                    "text": "متن رأی",
                    "source_uri": "https://example.test/decision/224",
                    "node_type": "decision",
                    "source_datasets": ["unanimity"],
                    "access_status": "available",
                    "relation_types": ["REFERENCES"],
                    "hops": 1,
                }
            ]
        )


def test_neo4j_expansion_is_parameterized_allowlisted_and_capped() -> None:
    driver = FakeDriver()
    search = Neo4jLegalGraphSearch(
        uri="bolt://unused",
        username="neo4j",
        password="unused",
        driver=driver,
    )

    results = search.expand(["article:10"], depth=99, limit=999)

    assert driver.parameters["entity_ids"] == ["article:10"]
    assert driver.parameters["limit"] == 100
    assert "REFERENCES" in driver.parameters["allowed_relationships"]
    assert "article:10" not in str(driver.query)
    assert "*1..3" in str(driver.query)
    assert results[0].authority is AuthorityTier.PRIMARY
    assert results[0].metadata["relationship_types"] == ["REFERENCES"]
