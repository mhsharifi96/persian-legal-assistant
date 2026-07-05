from legal_assistant.application.services.hybrid_retriever import HybridRetriever
from legal_assistant.domain.models import LegalChunk, LegalHierarchy, RetrievedContext
from legal_assistant.infrastructure.fakes import (
    FakeEmbeddingModel,
    InMemoryGraphRepository,
    InMemoryVectorStoreRepository,
)


def test_hybrid_retriever_merges_vector_results_with_graph_neighbors():
    embeddings = FakeEmbeddingModel()
    vector_store = InMemoryVectorStoreRepository()
    graph_store = InMemoryGraphRepository()
    chunk = LegalChunk(
        id="chunk-1",
        document_id="law",
        text="ماده ۱۰ قراردادهای خصوصی نافذ است.",
        hierarchy=LegalHierarchy(article_number="10"),
        citations=("قانون مدنی، ماده 10",),
        metadata={"jurisdiction": "IR"},
    )
    vector_store.upsert_chunks([chunk], embeddings.embed_texts([chunk.text]))
    graph_store.add_context_neighbor(
        "chunk-1",
        RetrievedContext(
            chunk_id="chunk-neighbor",
            text="اصل آزادی قراردادها",
            score=0.25,
            source="graph",
            hierarchy=LegalHierarchy(),
            graph_neighbors=("concept:contract-freedom",),
        ),
    )

    contexts = HybridRetriever(embeddings, vector_store, graph_store).retrieve(
        "قرارداد خصوصی", filters={"jurisdiction": "IR"}, top_k=5
    )

    assert {context.chunk_id for context in contexts} == {"chunk-1", "chunk-neighbor"}
    assert contexts[0].source == "vector"
