from legal_assistant.application.services.ingestion import DocumentIngestionService
from legal_assistant.domain.errors import GraphExtractionError
from legal_assistant.domain.models import GraphEntity, GraphExtraction, LegalDocument
from legal_assistant.infrastructure.chunkers import PersianLegalHierarchicalChunker
from legal_assistant.infrastructure.fakes import (
    FailingBatchEmbeddingModel,
    FakeDocumentParser,
    FakeEmbeddingModel,
    FakeGraphExtractor,
    InMemoryGraphRepository,
    InMemoryIngestionErrorSink,
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
    assert result.errors == ()


def test_ingestion_isolates_graph_extraction_failures_per_chunk() -> None:
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
    error_sink = InMemoryIngestionErrorSink()

    class FailOnceGraphExtractor:
        def __init__(self) -> None:
            self.calls = 0

        def extract(self, chunk):
            self.calls += 1
            if self.calls == 1:
                raise GraphExtractionError("boom")
            return GraphExtraction()

    service = DocumentIngestionService(
        parser=FakeDocumentParser([document]),
        chunker=PersianLegalHierarchicalChunker(),
        embeddings=FakeEmbeddingModel(),
        vector_store=vector_store,
        graph_store=graph_store,
        graph_extractor=FailOnceGraphExtractor(),
        error_sink=error_sink,
    )

    result = service.ingest("file:///law.txt")

    assert result.chunk_count == 2
    assert len(vector_store.chunks) == 2
    assert len(result.errors) == 1
    assert result.errors[0].stage == "graph_extraction"
    assert len(error_sink.errors) == 1


def test_ingestion_isolates_embedding_failures_per_chunk() -> None:
    document = LegalDocument(
        id="law",
        title="قانون نمونه",
        source_uri="file:///law.txt",
        jurisdiction="IR",
        document_type="law",
        text="ماده ۱ - متن اول\nتبصره ۱ - متن دوم",
    )
    poisoned_text = PersianLegalHierarchicalChunker().chunk(document)[0].text
    vector_store = InMemoryVectorStoreRepository()
    graph_store = InMemoryGraphRepository()
    error_sink = InMemoryIngestionErrorSink()

    service = DocumentIngestionService(
        parser=FakeDocumentParser([document]),
        chunker=PersianLegalHierarchicalChunker(),
        embeddings=FailingBatchEmbeddingModel([poisoned_text]),
        vector_store=vector_store,
        graph_store=graph_store,
        error_sink=error_sink,
    )

    result = service.ingest("file:///law.txt")

    assert result.chunk_count == 2
    assert len(vector_store.chunks) == 1
    assert len(result.errors) == 1
    assert result.errors[0].stage == "embedding"
    assert len(error_sink.errors) == 1
