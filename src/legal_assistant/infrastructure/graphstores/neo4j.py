from __future__ import annotations

import json
import re
from typing import Any, Sequence

from langchain_neo4j import Neo4jGraph
from langsmith import trace

from legal_assistant.domain.models import (
    GraphEntity,
    GraphRelation,
    LegalChunk,
    LegalHierarchy,
    RetrievedContext,
)

_RELATION_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class Neo4jGraphRepository:
    """LangChain Neo4j adapter with explicit source-chunk graph links."""

    def __init__(
        self,
        *,
        uri: str,
        username: str,
        password: str,
        database: str = "neo4j",
        graph: Neo4jGraph | None = None,
    ) -> None:
        self._graph = graph or Neo4jGraph(
            url=uri,
            username=username,
            password=password,
            database=database,
            refresh_schema=False,
        )
        if graph is None:
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create indexes required for bounded idempotent merge performance."""
        self._graph.query(
            "CREATE CONSTRAINT legal_entity_entity_id IF NOT EXISTS "
            "FOR (node:LegalEntity) REQUIRE node.entity_id IS UNIQUE"
        )
        self._graph.query(
            "CREATE CONSTRAINT legal_chunk_chunk_id IF NOT EXISTS "
            "FOR (chunk:LegalChunk) REQUIRE chunk.chunk_id IS UNIQUE"
        )

    def upsert_entities(self, entities: Sequence[GraphEntity]) -> None:
        with trace(
            "neo4j-upsert-legal-entities",
            run_type="tool",
            inputs={"entity_ids": [entity.id for entity in entities]},
        ):
            self._upsert_entities_impl(entities)

    def _upsert_entities_impl(self, entities: Sequence[GraphEntity]) -> None:
        if not entities:
            return
        self._graph.query(
            """
            UNWIND $entities AS entity
            MERGE (node:LegalEntity {entity_id: entity.id})
            SET node.type = entity.type,
                node.name = entity.name,
                node.properties_json = entity.properties_json
            """,
            {
                "entities": [
                    {
                        "id": entity.id,
                        "type": entity.type,
                        "name": entity.name,
                        "properties_json": json.dumps(
                            entity.properties, ensure_ascii=False
                        ),
                    }
                    for entity in entities
                ]
            },
        )

    def upsert_relations(self, relations: Sequence[GraphRelation]) -> None:
        with trace(
            "neo4j-upsert-legal-relations",
            run_type="tool",
            inputs={"relation_count": len(relations)},
        ):
            self._upsert_relations_impl(relations)

    def _upsert_relations_impl(self, relations: Sequence[GraphRelation]) -> None:
        by_type: dict[str, list[GraphRelation]] = {}
        for relation in relations:
            if not _RELATION_TYPE_RE.fullmatch(relation.type):
                raise ValueError(f"Unsafe Neo4j relation type: {relation.type}")
            by_type.setdefault(relation.type, []).append(relation)
        for relation_type, typed_relations in by_type.items():
            self._graph.query(
                f"""
                UNWIND $relations AS relation
                MERGE (source:LegalEntity {{entity_id: relation.source_id}})
                MERGE (target:LegalEntity {{entity_id: relation.target_id}})
                MERGE (source)-[edge:{relation_type}]->(target)
                SET edge.properties_json = relation.properties_json
                """,
                {
                    "relations": [
                        {
                            "source_id": relation.source_id,
                            "target_id": relation.target_id,
                            "properties_json": json.dumps(
                                relation.properties, ensure_ascii=False
                            ),
                        }
                        for relation in typed_relations
                    ]
                },
            )

    def link_chunk(self, chunk: LegalChunk, entity_ids: Sequence[str]) -> None:
        self.link_chunks([(chunk, entity_ids)])

    def link_chunks(
        self, items: Sequence[tuple[LegalChunk, Sequence[str]]]
    ) -> None:
        if not items:
            return
        with trace(
            "neo4j-link-legal-chunks",
            run_type="tool",
            inputs={"chunk_count": len(items)},
        ):
            for start in range(0, len(items), 500):
                self._link_chunks_impl(items[start : start + 500])

    def _link_chunks_impl(
        self, items: Sequence[tuple[LegalChunk, Sequence[str]]]
    ) -> None:
        self._graph.query(
            """
            UNWIND $chunks AS item
            MERGE (chunk:LegalChunk {chunk_id: item.chunk_id})
            SET chunk.document_id = item.document_id,
                chunk.text = item.text,
                chunk.hierarchy_json = item.hierarchy_json,
                chunk.citations = item.citations,
                chunk.metadata_json = item.metadata_json
            WITH chunk, item
            OPTIONAL MATCH (chunk)-[old:MENTIONS]->()
            DELETE old
            WITH DISTINCT chunk, item
            UNWIND item.entity_ids AS entity_id
            MATCH (entity:LegalEntity {entity_id: entity_id})
            MERGE (chunk)-[:MENTIONS]->(entity)
            """,
            {
                "chunks": [
                    {
                        "chunk_id": chunk.id,
                        "document_id": chunk.document_id,
                        "text": chunk.text,
                        "hierarchy_json": json.dumps(
                            self._hierarchy_to_dict(chunk.hierarchy),
                            ensure_ascii=False,
                        ),
                        "citations": list(chunk.citations),
                        "metadata_json": json.dumps(
                            chunk.metadata, ensure_ascii=False
                        ),
                        "entity_ids": list(dict.fromkeys(entity_ids)),
                    }
                    for chunk, entity_ids in items
                ]
            },
        )

    def expand_context(
        self, chunk_ids: Sequence[str], *, depth: int, limit: int | None = None
    ) -> list[RetrievedContext]:
        with trace(
            "neo4j-expand-legal-context",
            run_type="retriever",
            inputs={"chunk_ids": list(chunk_ids), "depth": depth, "limit": limit},
        ):
            return self._expand_context_impl(chunk_ids, depth=depth, limit=limit)

    def _expand_context_impl(
        self, chunk_ids: Sequence[str], *, depth: int, limit: int | None = None
    ) -> list[RetrievedContext]:
        if not chunk_ids:
            return []
        safe_depth = max(0, min(int(depth), 5))
        rows = self._graph.query(
            f"""
            MATCH (seed:LegalChunk)-[:MENTIONS]->(start:LegalEntity)
            WHERE seed.chunk_id IN $chunk_ids
            MATCH path=(start)-[*0..{safe_depth}]-(neighbor:LegalEntity)
            MATCH (chunk:LegalChunk)-[:MENTIONS]->(neighbor)
            WHERE NOT chunk.chunk_id IN $chunk_ids
            WITH chunk, collect(DISTINCT neighbor.entity_id) AS neighbor_ids,
                 min(length(path)) AS hops
            RETURN chunk.chunk_id AS chunk_id,
                   chunk.text AS text,
                   chunk.hierarchy_json AS hierarchy_json,
                   chunk.citations AS citations,
                   chunk.metadata_json AS metadata_json,
                   neighbor_ids,
                   hops
            ORDER BY hops ASC, chunk.chunk_id ASC
            LIMIT $limit
            """,
            {"chunk_ids": list(chunk_ids), "limit": limit or 1000},
        )
        return [self._row_to_context(row) for row in rows]

    @staticmethod
    def _hierarchy_to_dict(hierarchy: LegalHierarchy) -> dict[str, str | None]:
        return {
            "book": hierarchy.book,
            "bab": hierarchy.bab,
            "fasl": hierarchy.fasl,
            "mabhas": hierarchy.mabhas,
            "goftar": hierarchy.goftar,
            "article_number": hierarchy.article_number,
            "note_number": hierarchy.note_number,
        }

    @staticmethod
    def _row_to_context(row: dict[str, Any]) -> RetrievedContext:
        hierarchy = json.loads(str(row.get("hierarchy_json") or "{}"))
        metadata = json.loads(str(row.get("metadata_json") or "{}"))
        hops = int(row.get("hops") or 0)
        return RetrievedContext(
            chunk_id=str(row["chunk_id"]),
            text=str(row.get("text", "")),
            score=1.0 / (1 + hops),
            source="graph",
            hierarchy=LegalHierarchy(**hierarchy),
            citations=tuple(str(item) for item in row.get("citations") or []),
            graph_neighbors=tuple(
                str(item) for item in row.get("neighbor_ids") or []
            ),
            metadata=metadata,
        )
