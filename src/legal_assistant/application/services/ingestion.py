from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from legal_assistant.application.ports import (
    DocumentParserPort,
    DocumentStore,
    EmbeddingModelPort,
    GraphExtractorPort,
    GraphRepository,
    IngestionErrorSink,
    LegalChunkerPort,
    VectorStoreRepository,
)
from legal_assistant.domain.errors import GraphExtractionError
from legal_assistant.domain.models import (
    GraphEntity,
    GraphRelation,
    IngestionErrorRecord,
    LegalChunk,
)


@dataclass(frozen=True)
class IngestionResult:
    document_count: int
    chunk_count: int
    graph_entity_count: int
    graph_relation_count: int
    errors: tuple[IngestionErrorRecord, ...] = ()


class DocumentIngestionService:
    def __init__(
        self,
        parser: DocumentParserPort,
        chunker: LegalChunkerPort,
        embeddings: EmbeddingModelPort | None = None,
        vector_store: VectorStoreRepository | None = None,
        graph_store: GraphRepository | None = None,
        graph_extractor: GraphExtractorPort | None = None,
        document_store: DocumentStore | None = None,
        vector_chunk_filter: Callable[[LegalChunk], bool] | None = None,
        error_sink: IngestionErrorSink | None = None,
        embedding_batch_size: int = 64,
    ) -> None:
        self._parser = parser
        self._chunker = chunker
        self._embeddings = embeddings
        self._vector_store = vector_store
        self._graph_store = graph_store
        self._graph_extractor = graph_extractor
        self._document_store = document_store
        self._vector_chunk_filter = vector_chunk_filter
        self._error_sink = error_sink
        self._embedding_batch_size = embedding_batch_size
        if (embeddings is None) != (vector_store is None):
            raise ValueError("embeddings and vector_store must be configured together")
        if graph_extractor is not None and graph_store is None:
            raise ValueError("graph_store is required when graph_extractor is configured")

    def ingest(self, source_uri: str) -> IngestionResult:
        documents = self._parser.parse(source_uri)
        chunks: list[LegalChunk] = []
        chunks_by_document: dict[str, list[LegalChunk]] = {}
        for document in documents:
            document_chunks = self._chunker.chunk(document)
            chunks.extend(document_chunks)
            chunks_by_document[document.id] = document_chunks

        if self._document_store is not None:
            self._document_store.save_documents(
                [
                    (document, chunks_by_document.get(document.id, ()))
                    for document in documents
                ]
            )

        errors: list[IngestionErrorRecord] = []

        vector_chunks = (
            [chunk for chunk in chunks if self._vector_chunk_filter(chunk)]
            if self._vector_chunk_filter is not None
            else chunks
        )
        if vector_chunks and self._embeddings is not None and self._vector_store is not None:
            embedded_chunks, vectors, embedding_errors = self._embed_with_isolation(
                vector_chunks
            )
            errors.extend(embedding_errors)
            if embedded_chunks:
                self._vector_store.upsert_chunks(embedded_chunks, vectors)

        entity_count = 0
        relation_count = 0
        if self._graph_extractor is not None and self._graph_store is not None:
            entities_by_id: dict[str, GraphEntity] = {}
            relations: list[GraphRelation] = []
            chunk_links: list[tuple[LegalChunk, list[str]]] = []
            for chunk in chunks:
                try:
                    extraction = self._graph_extractor.extract(chunk)
                except GraphExtractionError as exc:
                    errors.append(
                        IngestionErrorRecord(
                            document_id=chunk.document_id,
                            chunk_id=chunk.id,
                            stage="graph_extraction",
                            error_message=str(exc),
                        )
                    )
                    continue
                for entity in extraction.entities:
                    entities_by_id[entity.id] = entity
                relations.extend(extraction.relations)
                chunk_links.append(
                    (chunk, [entity.id for entity in extraction.entities])
                )
                entity_count += len(extraction.entities)
                relation_count += len(extraction.relations)
            self._graph_store.upsert_entities(list(entities_by_id.values()))
            self._graph_store.upsert_relations(relations)
            self._graph_store.link_chunks(chunk_links)

        if self._error_sink is not None:
            for error in errors:
                self._error_sink.record(error)

        return IngestionResult(
            document_count=len(documents),
            chunk_count=len(chunks),
            graph_entity_count=entity_count,
            graph_relation_count=relation_count,
            errors=tuple(errors),
        )

    def _embed_with_isolation(
        self, chunks: list[LegalChunk]
    ) -> tuple[list[LegalChunk], list[list[float]], list[IngestionErrorRecord]]:
        embeddings = self._embeddings
        if embeddings is None:
            raise RuntimeError("embedding model is not configured")
        embedded_chunks: list[LegalChunk] = []
        vectors: list[list[float]] = []
        errors: list[IngestionErrorRecord] = []

        for start in range(0, len(chunks), self._embedding_batch_size):
            batch = chunks[start : start + self._embedding_batch_size]
            try:
                batch_vectors = embeddings.embed_texts(
                    [chunk.text for chunk in batch]
                )
            except Exception as batch_exc:
                for chunk in batch:
                    try:
                        vector = embeddings.embed_query(chunk.text)
                    except Exception as item_exc:
                        errors.append(
                            IngestionErrorRecord(
                                document_id=chunk.document_id,
                                chunk_id=chunk.id,
                                stage="embedding",
                                error_message=str(item_exc) or str(batch_exc),
                            )
                        )
                        continue
                    embedded_chunks.append(chunk)
                    vectors.append(vector)
                continue
            embedded_chunks.extend(batch)
            vectors.extend(batch_vectors)

        return embedded_chunks, vectors, errors
