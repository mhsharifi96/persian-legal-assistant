from legal_assistant.application.services.hybrid_retriever import HybridRetriever
from legal_assistant.domain.models import LegalChunk, LegalHierarchy, RetrievedContext
from legal_assistant.domain.models import GraphEntity, GraphRelation
from legal_assistant.infrastructure.fakes import (
    FakeEmbeddingModel,
    InMemoryGraphRepository,
    InMemoryVectorStoreRepository,
)


def test_hybrid_retriever_merges_vector_results_with_graph_neighbors() -> None:
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


def test_hybrid_retriever_fuses_by_rank_not_raw_score() -> None:
    retriever = HybridRetriever(
        FakeEmbeddingModel(), InMemoryVectorStoreRepository(), InMemoryGraphRepository()
    )
    vector_contexts = [
        RetrievedContext(
            chunk_id="v-top", text="a", score=0.9, source="vector", hierarchy=LegalHierarchy()
        ),
        RetrievedContext(
            chunk_id="v-second", text="b", score=0.5, source="vector", hierarchy=LegalHierarchy()
        ),
    ]
    graph_contexts = [
        RetrievedContext(
            chunk_id="g-only", text="c", score=999.0, source="graph", hierarchy=LegalHierarchy()
        ),
        RetrievedContext(
            chunk_id="v-second", text="b", score=0.4, source="graph", hierarchy=LegalHierarchy()
        ),
    ]

    merged = retriever._merge_contexts(vector_contexts, graph_contexts, top_k=3)

    ranked_ids = [context.chunk_id for context in merged]
    assert ranked_ids[0] == "v-second"
    assert ranked_ids.index("g-only") > 0


def test_hybrid_retriever_caps_graph_fanout() -> None:
    embeddings = FakeEmbeddingModel()
    vector_store = InMemoryVectorStoreRepository()
    graph_store = InMemoryGraphRepository()
    chunk = LegalChunk(
        id="chunk-1",
        document_id="law",
        text="ماده ۱۰ نمونه",
        hierarchy=LegalHierarchy(article_number="10"),
        citations=(),
        metadata={},
    )
    vector_store.upsert_chunks([chunk], embeddings.embed_texts([chunk.text]))
    for index in range(30):
        graph_store.add_context_neighbor(
            "chunk-1",
            RetrievedContext(
                chunk_id=f"neighbor-{index}",
                text="x",
                score=0.1,
                source="graph",
                hierarchy=LegalHierarchy(),
            ),
        )

    contexts = HybridRetriever(
        embeddings, vector_store, graph_store, graph_fanout_limit=5
    ).retrieve("ماده", top_k=100)

    neighbor_ids = [context.chunk_id for context in contexts if context.chunk_id.startswith("neighbor-")]
    assert len(neighbor_ids) == 5


def test_in_memory_graph_expands_between_chunks_linked_by_entities() -> None:
    graph_store = InMemoryGraphRepository()
    source = LegalChunk(
        id="source",
        document_id="law",
        text="ماده ۱۰",
        hierarchy=LegalHierarchy(article_number="10"),
        citations=("قانون مدنی، ماده ۱۰",),
        metadata={"jurisdiction": "IR"},
    )
    neighbor = LegalChunk(
        id="neighbor",
        document_id="law",
        text="ماده ۲۱۹",
        hierarchy=LegalHierarchy(article_number="219"),
        citations=("قانون مدنی، ماده ۲۱۹",),
        metadata={"jurisdiction": "IR"},
    )
    entities = [
        GraphEntity(id="article:10", type="Article", name="ماده ۱۰"),
        GraphEntity(id="article:219", type="Article", name="ماده ۲۱۹"),
    ]
    graph_store.upsert_entities(entities)
    graph_store.upsert_relations(
        [GraphRelation("article:10", "article:219", "REFERENCES")]
    )
    graph_store.link_chunk(source, ["article:10"])
    graph_store.link_chunk(neighbor, ["article:219"])

    contexts = graph_store.expand_context(["source"], depth=1)

    assert [context.chunk_id for context in contexts] == ["neighbor"]
    assert contexts[0].citations == neighbor.citations
