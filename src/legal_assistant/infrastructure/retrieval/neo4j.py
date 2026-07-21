from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, LiteralString, cast

from neo4j import GraphDatabase, Query

from legal_assistant.domain.research import LegalEvidence
from legal_assistant.infrastructure.retrieval.common import (
    classify_authority,
    preferred_source_type,
    string_list,
)

_ALLOWED_RELATIONSHIPS = (
    "ADJACENT_DECISION",
    "AFFIRMS_DECISION",
    "AMENDS",
    "ANSWERED_BY",
    "APPLIES",
    "CITES_DECISION",
    "CONTAINS",
    "DISTINGUISHES_DECISION",
    "HAS_ANSWER",
    "IMPLEMENTS",
    "INTERPRETS_AMENDMENT",
    "ISSUED_BY",
    "LINKS_TO",
    "LISTS",
    "NEXT_DECISION",
    "OVERRULES_DECISION",
    "PREVIOUS_DECISION",
    "REFERENCES",
    "REPEALS",
    "REPEALS_OR_DISAPPLIES",
    "TAGGED_WITH",
)


class Neo4jLegalGraphSearch:
    """Bounded traversal over allowlisted relationships; accepts no raw Cypher."""

    def __init__(
        self,
        *,
        uri: str,
        username: str,
        password: str,
        database: str = "neo4j",
        timeout_seconds: float = 15.0,
        driver: Any | None = None,
    ) -> None:
        self._driver = driver or GraphDatabase.driver(uri, auth=(username, password))
        self._owns_driver = driver is None
        self._database = database
        self._timeout_seconds = timeout_seconds

    def close(self) -> None:
        if self._owns_driver:
            self._driver.close()

    def expand(
        self,
        entity_ids: Sequence[str],
        *,
        depth: int,
        limit: int,
    ) -> list[LegalEvidence]:
        normalized_ids = list(dict.fromkeys(value.strip() for value in entity_ids))[:50]
        normalized_ids = [value for value in normalized_ids if value]
        if not normalized_ids or limit <= 0:
            return []
        safe_depth = max(1, min(int(depth), 3))
        safe_limit = max(1, min(int(limit), 100))
        cypher = f"""
        MATCH (seed:LegalEntity)
        WHERE seed.entity_id IN $entity_ids
        MATCH path=(seed)-[*1..{safe_depth}]-(neighbor:LegalEntity)
        WHERE all(edge IN relationships(path)
                  WHERE type(edge) IN $allowed_relationships)
          AND neighbor.entity_id IS NOT NULL
        WITH neighbor, min(length(path)) AS hops,
             head(collect([edge IN relationships(path) | type(edge)])) AS relation_types
        RETURN neighbor.entity_id AS entity_id,
               labels(neighbor) AS labels,
               coalesce(neighbor.title, neighbor.name, neighbor.entity_id) AS title,
               coalesce(neighbor.text, '') AS text,
               coalesce(neighbor.url, neighbor.page_url, neighbor.profile_url, '') AS source_uri,
               coalesce(neighbor.node_type, neighbor.type, '') AS node_type,
               coalesce(neighbor.source_datasets, []) AS source_datasets,
               coalesce(neighbor.access_status, '') AS access_status,
               relation_types,
               hops
        ORDER BY hops ASC, entity_id ASC
        LIMIT $limit
        """
        result = self._driver.execute_query(
            # The only interpolation is ``safe_depth`` clamped above to 1..3;
            # all caller-provided values remain query parameters.
            Query(cast(LiteralString, cypher), timeout=self._timeout_seconds),
            entity_ids=normalized_ids,
            allowed_relationships=list(_ALLOWED_RELATIONSHIPS),
            limit=safe_limit,
            database_=self._database,
            routing_="r",
        )
        records = getattr(result, "records", None)
        if records is None:
            records = result[0]
        return [item for record in records if (item := self._to_evidence(record))]

    @staticmethod
    def _to_evidence(record: Any) -> LegalEvidence | None:
        data: Mapping[str, Any]
        if isinstance(record, Mapping):
            data = record
        else:
            data = record.data()
        entity_id = str(data.get("entity_id") or "").strip()
        text = str(data.get("text") or "").strip()
        if not entity_id or not text:
            return None
        labels = string_list(data.get("labels", []))
        hops = max(1, int(data.get("hops") or 1))
        node_type = str(data.get("node_type") or "").strip()
        return LegalEvidence(
            evidence_id=f"neo4j:{entity_id}",
            entity_id=entity_id,
            title=str(data.get("title") or entity_id).strip(),
            text=text,
            source_type=node_type or preferred_source_type(labels),
            authority=classify_authority(
                labels,
                access_status=str(data.get("access_status") or ""),
            ),
            score=1.0 / (1.0 + hops),
            source_uri=str(data.get("source_uri") or "").strip(),
            metadata={
                "labels": labels,
                "source_datasets": string_list(data.get("source_datasets", [])),
                "relationship_types": string_list(data.get("relation_types", [])),
                "hops": hops,
            },
        )
