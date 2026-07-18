from __future__ import annotations

from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid5

from langchain_qdrant import QdrantVectorStore
from langsmith import trace
from qdrant_client import QdrantClient, models

from legal_assistant.domain.models import LegalChunk, LegalHierarchy, RetrievedContext


class QdrantVectorStoreRepository:
    """Qdrant adapter for vectors already produced through the embedding port.

    The application passes precomputed vectors into this repository, avoiding a
    second paid embedding call during indexing. Payloads follow LangChain's
    ``page_content``/``metadata`` convention, so the collection remains usable
    through ``langchain-qdrant`` in other workflows.
    """

    def __init__(
        self,
        *,
        url: str,
        collection_name: str,
        api_key: str = "",
        client: QdrantClient | None = None,
    ) -> None:
        self._client = client or QdrantClient(url=url, api_key=api_key or None)
        self._collection_name = collection_name
        self._vector_store = QdrantVectorStore(
            client=self._client,
            collection_name=collection_name,
            embedding=None,
            validate_embeddings=False,
            validate_collection_config=False,
        )

    def upsert_chunks(
        self, chunks: Sequence[LegalChunk], vectors: Sequence[list[float]]
    ) -> None:
        with trace(
            "qdrant-upsert-legal-chunks",
            run_type="tool",
            inputs={"chunk_ids": [chunk.id for chunk in chunks]},
        ):
            self._upsert_chunks_impl(chunks, vectors)

    def _upsert_chunks_impl(
        self, chunks: Sequence[LegalChunk], vectors: Sequence[list[float]]
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if not chunks:
            return
        dimensions = len(vectors[0])
        if dimensions <= 0 or any(len(vector) != dimensions for vector in vectors):
            raise ValueError("all vectors must have the same positive dimension")
        self._ensure_collection(dimensions)
        for start in range(0, len(chunks), 256):
            chunk_batch = chunks[start : start + 256]
            vector_batch = vectors[start : start + 256]
            points = [
                models.PointStruct(
                    id=str(uuid5(NAMESPACE_URL, chunk.id)),
                    vector=vector,
                    payload={
                        "page_content": chunk.text,
                        "metadata": self._chunk_metadata(chunk),
                    },
                )
                for chunk, vector in zip(chunk_batch, vector_batch, strict=True)
            ]
            self._client.upsert(
                collection_name=self._collection_name,
                points=points,
                wait=True,
            )

    def search(
        self,
        query_vector: list[float],
        *,
        filters: dict[str, Any] | None,
        top_k: int,
    ) -> list[RetrievedContext]:
        with trace(
            "qdrant-search-legal-chunks",
            run_type="retriever",
            inputs={"filters": filters or {}, "top_k": top_k},
        ):
            return self._search_impl(query_vector, filters=filters, top_k=top_k)

    def _search_impl(
        self,
        query_vector: list[float],
        *,
        filters: dict[str, Any] | None,
        top_k: int,
    ) -> list[RetrievedContext]:
        if top_k <= 0 or not self._client.collection_exists(self._collection_name):
            return []
        result = self._vector_store.similarity_search_with_score_by_vector(
            query_vector,
            k=top_k,
            filter=self._filter(filters),
        )
        contexts: list[RetrievedContext] = []
        for document, score in result:
            metadata = dict(document.metadata)
            hierarchy_raw = dict(metadata.pop("hierarchy", {}) or {})
            citations = tuple(str(item) for item in metadata.pop("citations", []))
            chunk_id = str(metadata.pop("chunk_id", metadata.get("_id", "")))
            metadata.pop("_id", None)
            metadata.pop("_collection_name", None)
            contexts.append(
                RetrievedContext(
                    chunk_id=chunk_id,
                    text=document.page_content,
                    score=float(score),
                    source="vector",
                    hierarchy=LegalHierarchy(**hierarchy_raw),
                    citations=citations,
                    metadata=metadata,
                )
            )
        return contexts

    def _ensure_collection(self, dimensions: int) -> None:
        if self._client.collection_exists(self._collection_name):
            collection = self._client.get_collection(self._collection_name)
            vectors = collection.config.params.vectors
            configured_size = getattr(vectors, "size", None)
            if configured_size is not None and configured_size != dimensions:
                raise ValueError(
                    f"Qdrant collection vector size is {configured_size}, expected {dimensions}"
                )
            return
        self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config=models.VectorParams(
                size=dimensions, distance=models.Distance.COSINE
            ),
        )

    @staticmethod
    def _chunk_metadata(chunk: LegalChunk) -> dict[str, Any]:
        hierarchy = {
            "book": chunk.hierarchy.book,
            "bab": chunk.hierarchy.bab,
            "fasl": chunk.hierarchy.fasl,
            "mabhas": chunk.hierarchy.mabhas,
            "goftar": chunk.hierarchy.goftar,
            "article_number": chunk.hierarchy.article_number,
            "note_number": chunk.hierarchy.note_number,
        }
        return {
            **chunk.metadata,
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "hierarchy": hierarchy,
            "citations": list(chunk.citations),
        }

    @staticmethod
    def _filter(filters: dict[str, Any] | None) -> models.Filter | None:
        if not filters:
            return None
        return models.Filter(
            must=[
                models.FieldCondition(
                    key=f"metadata.{key}", match=models.MatchValue(value=value)
                )
                for key, value in filters.items()
            ]
        )
