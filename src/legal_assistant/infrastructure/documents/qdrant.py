from __future__ import annotations

import uuid
from collections.abc import Sequence

from qdrant_client import QdrantClient, models

from legal_assistant.application.document_ingestion import DocumentChunk


class QdrantDocumentVectorStore:
    def __init__(
        self,
        *,
        url: str,
        collection_name: str,
        api_key: str | None = None,
        client: QdrantClient | None = None,
    ) -> None:
        self._client = client or QdrantClient(url=url, api_key=api_key or None)
        self._collection_name = collection_name

    def replace_document(
        self,
        document_id: str,
        chunks: Sequence[DocumentChunk],
        vectors: Sequence[list[float]],
        *,
        dimension: int,
    ) -> None:
        self._ensure_collection(dimension)
        self._client.delete(
            collection_name=self._collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
            wait=True,
        )
        points = [
            models.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.id)),
                vector=vector,
                payload={
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "title": chunk.title,
                    "text": chunk.text,
                    "chunk_index": chunk.index,
                    "chunk_count": chunk.count,
                    "file_url": chunk.file_url,
                    "local_address_file": chunk.local_address_file,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        self._client.upsert(
            collection_name=self._collection_name,
            points=points,
            wait=True,
        )

    def _ensure_collection(self, dimension: int) -> None:
        if not self._client.collection_exists(self._collection_name):
            self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=models.VectorParams(
                    size=dimension,
                    distance=models.Distance.COSINE,
                ),
            )
            return
        info = self._client.get_collection(self._collection_name)
        vectors = info.config.params.vectors
        existing_size = getattr(vectors, "size", None)
        if existing_size is not None and existing_size != dimension:
            raise ValueError(
                f"Qdrant collection vector size is {existing_size}, expected {dimension}"
            )
