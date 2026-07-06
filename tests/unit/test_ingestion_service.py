from legal_assistant.application.services.ingestion import DocumentIngestionService
from legal_assistant.domain.models import GraphEntity, GraphExtraction, LegalDocument
from legal_assistant.infrastructure.chunkers import PersianLegalHierarchicalChunker
from legal_assistant.infrastructure.fakes import (
    FakeDocumentParser,
    FakeEmbeddingModel,
    FakeGraphExtractor,
    InMemoryGraphRepository,
    InMemoryVectorStoreRepository,
)


def test_ingestion_parses_chunks_embeds_and_writes_graph() -> None:
    document = LegalDocument(
        id="law",
        title="قانون نمونه",
        source_uri="file:///law.txt",
        jurisdiction="IR",
        document_type="law",
        text="ماده ۱ - متن ماده\nتبصره ۱ - متن تبصره",
    )
    vector_store = InMemoryVectorStoreRepository()
    graph_store = InMemoryGraphRepository()
    graph_extractor = FakeGraphExtractor(
        GraphExtraction(
            entities=(GraphEntity(id="article:law:1", type="Article", name="ماده ۱"),)
        )
    )
    service = DocumentIngestionService(
        parser=FakeDocumentParser([document]),
        chunker=PersianLegalHierarchicalChunker(),
        embeddings=FakeEmbeddingModel(),
        vector_store=vector_store,
        graph_store=graph_store,
        graph_extractor=graph_extractor,
    )

    result = service.ingest("file:///law.txt")

    assert result.document_count == 1
    assert result.chunk_count == 2
    assert result.graph_entity_count == 2
    assert len(vector_store.chunks) == 2
    assert graph_store.entities["article:law:1"].type == "Article"
