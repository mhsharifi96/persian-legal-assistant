from __future__ import annotations

from typing import Any

from qdrant_client import QdrantClient

from legal_assistant.application.ports import EmbeddingModelPort
from legal_assistant.domain.research import LegalEvidence
from legal_assistant.infrastructure.retrieval.common import (
    classify_authority,
    preferred_source_type,
    string_list,
)


class QdrantLegalVectorSearch:
    """Semantic search over the current flat graph/PDF Qdrant payloads."""

    def __init__(
        self,
        embeddings: EmbeddingModelPort,
        *,
        url: str,
        collection_name: str,
        api_key: str = "",
        client: Any | None = None,
    ) -> None:
        self._embeddings = embeddings
        self._client = client or QdrantClient(url=url, api_key=api_key or None)
        self._owns_client = client is None
        self._collection_name = collection_name

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def search(self, query: str, *, top_k: int) -> list[LegalEvidence]:
        if top_k <= 0 or not self._client.collection_exists(self._collection_name):
            return []
        response = self._client.query_points(
            collection_name=self._collection_name,
            query=self._embeddings.embed_query(query),
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )
        points = getattr(response, "points", response)
        evidence: list[LegalEvidence] = []
        for point in points:
            payload = dict(getattr(point, "payload", None) or {})
            item = self._to_evidence(point, payload)
            if item is not None:
                evidence.append(item)
        return evidence

    @staticmethod
    def _to_evidence(point: Any, payload: dict[str, Any]) -> LegalEvidence | None:
        nested_metadata = payload.get("metadata")
        metadata = dict(nested_metadata) if isinstance(nested_metadata, dict) else {}
        labels = string_list(payload.get("labels", metadata.get("labels", [])))
        entity_id = str(
            payload.get("entity_id")
            or metadata.get("entity_id")
            or payload.get("chunk_id")
            or metadata.get("chunk_id")
            or payload.get("document_id")
            or metadata.get("document_id")
            or ""
        ).strip()
        point_id = str(getattr(point, "id", "")).strip()
        text = str(
            payload.get("text")
            or payload.get("page_content")
            or metadata.get("text")
            or ""
        ).strip()
        if not entity_id or not point_id or not text:
            return None
        title = str(
            payload.get("title")
            or metadata.get("title")
            or payload.get("name")
            or entity_id
        ).strip()
        source_uri = str(
            payload.get("url")
            or payload.get("file_url")
            or metadata.get("source_uri")
            or metadata.get("file_url")
            or ""
        ).strip()
        access_status = str(
            payload.get("access_status") or metadata.get("access_status") or ""
        )
        source_type = str(
            payload.get("node_type")
            or metadata.get("document_type")
            or preferred_source_type(labels)
        )
        safe_metadata: dict[str, object] = {
            "labels": labels,
            "source_datasets": string_list(payload.get("source_datasets", [])),
            "chunk_index": int(payload.get("chunk_index") or 0),
            "chunk_count": int(payload.get("chunk_count") or 0),
        }
        return LegalEvidence(
            evidence_id=f"qdrant:{point_id}",
            entity_id=entity_id,
            title=title,
            text=text,
            source_type=source_type,
            authority=classify_authority(labels, access_status=access_status),
            score=float(getattr(point, "score", 0.0) or 0.0),
            source_uri=source_uri,
            metadata=safe_metadata,
        )
