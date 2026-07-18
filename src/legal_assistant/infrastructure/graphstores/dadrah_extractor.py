from __future__ import annotations

import hashlib

from legal_assistant.domain.models import (
    GraphEntity,
    GraphExtraction,
    GraphRelation,
    LegalChunk,
)


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.strip().casefold().encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{digest}"


class DadrahGraphExtractor:
    """Build a deterministic provenance graph without an LLM call."""

    def extract(self, chunk: LegalChunk) -> GraphExtraction:
        metadata = chunk.metadata
        request_id = str(metadata.get("request_id") or chunk.document_id)
        consultation_id = f"consultation:{request_id}"
        consultation = GraphEntity(
            id=consultation_id,
            type="Consultation",
            name=f"مشاوره {request_id}",
            properties={"source_uri": metadata.get("source_uri")},
        )
        entities: list[GraphEntity] = [consultation]
        relations: list[GraphRelation] = []

        if metadata.get("content_role") == "question":
            for tag_name in metadata.get("tags") or ():
                name = str(tag_name).strip()
                if not name:
                    continue
                tag_id = _stable_id("tag", name)
                entities.append(GraphEntity(id=tag_id, type="Topic", name=name))
                relations.append(
                    GraphRelation(
                        source_id=consultation_id,
                        target_id=tag_id,
                        type="HAS_TAG",
                    )
                )

        if metadata.get("content_role") == "answer":
            lawyer_name = str(metadata.get("lawyer_name") or "").strip()
            profile_url = str(metadata.get("lawyer_profile_url") or "").strip()
            if lawyer_name:
                lawyer_id = _stable_id("lawyer", profile_url or lawyer_name)
                entities.append(
                    GraphEntity(
                        id=lawyer_id,
                        type="Lawyer",
                        name=lawyer_name,
                        properties={
                            "city": metadata.get("lawyer_city"),
                            "profile_url": profile_url or None,
                        },
                    )
                )
                relations.append(
                    GraphRelation(
                        source_id=consultation_id,
                        target_id=lawyer_id,
                        type="ANSWERED_BY",
                    )
                )

        return GraphExtraction(entities=tuple(entities), relations=tuple(relations))
