from __future__ import annotations

from dataclasses import dataclass

from legal_assistant.application.ports import (
    DocumentParserPort,
    EmbeddingModelPort,
    GraphExtractorPort,
    GraphRepository,
    IngestionErrorSink,
    LegalChunkerPort,
    VectorStoreRepository,
)
from legal_assistant.domain.errors import GraphExtractionError
from legal_assistant.domain.models import IngestionErrorRecord, LegalChunk


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
        embeddings: EmbeddingModelPort,
        vector_store: VectorStoreRepository,
        graph_store: GraphRepository,
        graph_extractor: GraphExtractorPort | None = None,
        error_sink: IngestionErrorSink | None = None,
        embedding_batch_size: int = 64,
    ) -> None:
        self._parser = parser
        self._chunker = chunker
        self._embeddings = embeddings
        self._vector_store = vector_store
        self._graph_store = graph_store
        self._graph_extractor = graph_extractor
        self._error_sink = error_sink
        self._embedding_batch_size = embedding_batch_size

    def ingest(self, source_uri: str) -> IngestionResult:
        documents = self._parser.parse(source_uri)
        chunks: list[LegalChunk] = []
        for document in documents:
            chunks.extend(self._chunker.chunk(document))

        errors: list[IngestionErrorRecord] = []

        if chunks:
            embedded_chunks, vectors, embedding_errors = self._embed_with_isolation(chunks)
            errors.extend(embedding_errors)
            if embedded_chunks:
                self._vector_store.upsert_chunks(embedded_chunks, vectors)

        entity_count = 0
        relation_count = 0
        if self._graph_extractor is not None:
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
                self._graph_store.upsert_entities(extraction.entities)
                self._graph_store.upsert_relations(extraction.relations)
                self._graph_store.link_chunk(
                    chunk, [entity.id for entity in extraction.entities]
                )
                entity_count += len(extraction.entities)
                relation_count += len(extraction.relations)

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
        embedded_chunks: list[LegalChunk] = []
        vectors: list[list[float]] = []
        errors: list[IngestionErrorRecord] = []

        for start in range(0, len(chunks), self._embedding_batch_size):
            batch = chunks[start : start + self._embedding_batch_size]
            try:
                batch_vectors = self._embeddings.embed_texts(
                    [chunk.text for chunk in batch]
                )
            except Exception as batch_exc:
                for chunk in batch:
                    try:
                        vector = self._embeddings.embed_query(chunk.text)
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
