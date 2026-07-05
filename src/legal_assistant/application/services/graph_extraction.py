from __future__ import annotations

import json
from typing import Any

from legal_assistant.application.ports import LLMPort
from legal_assistant.domain.errors import GraphExtractionError
from legal_assistant.domain.models import GraphEntity, GraphExtraction, GraphRelation, LegalChunk


DEFAULT_ENTITY_TYPES = frozenset(
    {
        "Law",
        "Article",
        "Note",
        "Concept",
        "Penalty",
        "Court",
        "PersonRole",
        "Organization",
        "Procedure",
        "Deadline",
    }
)

DEFAULT_RELATION_TYPES = frozenset(
    {
        "CONTAINS",
        "REFERENCES",
        "AMENDS",
        "REPEALS",
        "DEFINES",
        "IMPOSES",
        "APPLIES_TO",
        "EXCEPTION_TO",
        "HAS_DEADLINE",
    }
)


class GraphExtractionService:
    def __init__(
        self,
        llm: LLMPort,
        *,
        allowed_entity_types: set[str] | None = None,
        allowed_relation_types: set[str] | None = None,
    ) -> None:
        self._llm = llm
        self._allowed_entity_types = allowed_entity_types or set(DEFAULT_ENTITY_TYPES)
        self._allowed_relation_types = allowed_relation_types or set(DEFAULT_RELATION_TYPES)

    def extract(self, chunk: LegalChunk) -> GraphExtraction:
        response = self._llm.complete(
            [
                {
                    "role": "system",
                    "content": "Extract a conservative legal knowledge graph as JSON.",
                },
                {"role": "user", "content": chunk.text},
            ],
            response_schema={"type": "object"},
        )
        try:
            return self._parse_response(response)
        except GraphExtractionError:
            repaired = self._llm.complete(
                [
                    {
                        "role": "system",
                        "content": "Repair this graph extraction into valid JSON only.",
                    },
                    {"role": "user", "content": str(response)},
                ],
                response_schema={"type": "object"},
            )
            return self._parse_response(repaired)

    def _parse_response(self, response: str | dict[str, Any]) -> GraphExtraction:
        data = json.loads(response) if isinstance(response, str) else response
        if not isinstance(data, dict):
            raise GraphExtractionError("Graph extraction response must be an object.")

        entities = tuple(self._parse_entity(item) for item in data.get("entities", []))
        entity_ids = {entity.id for entity in entities}
        relations = tuple(
            self._parse_relation(item, entity_ids)
            for item in data.get("relationships", data.get("relations", []))
        )
        return GraphExtraction(entities=entities, relations=relations)

    def _parse_entity(self, item: Any) -> GraphEntity:
        if not isinstance(item, dict):
            raise GraphExtractionError("Graph entity must be an object.")
        entity_type = str(item.get("type", ""))
        if entity_type not in self._allowed_entity_types:
            raise GraphExtractionError(f"Unsupported graph entity type: {entity_type}")
        return GraphEntity(
            id=str(item["id"]),
            type=entity_type,
            name=str(item["name"]),
            properties=dict(item.get("properties") or {}),
        )

    def _parse_relation(self, item: Any, entity_ids: set[str]) -> GraphRelation:
        if not isinstance(item, dict):
            raise GraphExtractionError("Graph relation must be an object.")
        relation_type = str(item.get("type", ""))
        if relation_type not in self._allowed_relation_types:
            raise GraphExtractionError(f"Unsupported graph relation type: {relation_type}")

        source_id = str(item["source_id"])
        target_id = str(item["target_id"])
        properties = dict(item.get("properties") or {})
        if source_id not in entity_ids or target_id not in entity_ids:
            properties["has_placeholder_endpoint"] = True

        return GraphRelation(
            source_id=source_id,
            target_id=target_id,
            type=relation_type,
            properties=properties,
        )
