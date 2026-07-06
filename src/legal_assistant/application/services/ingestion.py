from __future__ import annotations

from dataclasses import dataclass

from legal_assistant.application.ports import (
    DocumentParserPort,
    EmbeddingModelPort,
    GraphExtractorPort,
    GraphRepository,
    LegalChunkerPort,
    VectorStoreRepository,
)
from legal_assistant.domain.models import LegalChunk


@dataclass(frozen=True)
class IngestionResult:
    document_count: int
    chunk_count: int
    graph_entity_count: int
    graph_relation_count: int


class DocumentIngestionService:
    def __init__(
        self,
        parser: DocumentParserPort,
        chunker: LegalChunkerPort,
        embeddings: EmbeddingModelPort,
        vector_store: VectorStoreRepository,
        graph_store: GraphRepository,
        graph_extractor: GraphExtractorPort | None = None,
    ) -> None:
        self._parser = parser
        self._chunker = chunker
        self._embeddings = embeddings
        self._vector_store = vector_store
        self._graph_store = graph_store
        self._graph_extractor = graph_extractor

    def ingest(self, source_uri: str) -> IngestionResult:
        documents = self._parser.parse(source_uri)
        chunks: list[LegalChunk] = []
        for document in documents:
            chunks.extend(self._chunker.chunk(document))

        if chunks:
            vectors = self._embeddings.embed_texts([chunk.text for chunk in chunks])
            self._vector_store.upsert_chunks(chunks, vectors)

        entity_count = 0
        relation_count = 0
        if self._graph_extractor is not None:
            for chunk in chunks:
                extraction = self._graph_extractor.extract(chunk)
                self._graph_store.upsert_entities(extraction.entities)
                self._graph_store.upsert_relations(extraction.relations)
                entity_count += len(extraction.entities)
                relation_count += len(extraction.relations)

        return IngestionResult(
            document_count=len(documents),
            chunk_count=len(chunks),
            graph_entity_count=entity_count,
            graph_relation_count=relation_count,
        )
