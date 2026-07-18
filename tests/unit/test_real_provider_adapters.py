from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from langchain_neo4j import Neo4jGraph
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from qdrant_client import QdrantClient

from legal_assistant.domain.models import (
    GraphEntity,
    GraphRelation,
    LegalChunk,
    LegalHierarchy,
)
from legal_assistant.infrastructure.embeddings import OpenAIEmbeddingModel
from legal_assistant.infrastructure.graphstores import Neo4jGraphRepository
from legal_assistant.infrastructure.llms import OpenAILLM
from legal_assistant.infrastructure.vectorstores import QdrantVectorStoreRepository


class StubEmbeddings:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), 1.0]


@dataclass
class StubMessage:
    text: str


class StubChatModel:
    def __init__(self) -> None:
        self.bound: dict[str, Any] = {}
        self.configs: list[dict[str, Any]] = []

    def bind(self, **kwargs: Any) -> "StubChatModel":
        self.bound = kwargs
        return self

    def invoke(
        self, messages: list[dict[str, Any]], *, config: dict[str, Any]
    ) -> StubMessage:
        self.configs.append(config)
        if self.bound:
            return StubMessage('{"intent": "legal_advice"}')
        return StubMessage("پاسخ")


class StubNeo4jGraph:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def query(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append((query, params or {}))
        if "RETURN chunk.chunk_id" not in query:
            return []
        return [
            {
                "chunk_id": "neighbor-1",
                "text": "متن مرتبط",
                "hierarchy_json": '{"article_number": "10"}',
                "citations": ["قانون مدنی، ماده ۱۰"],
                "metadata_json": '{"jurisdiction": "IR"}',
                "neighbor_ids": ["concept:contract"],
                "hops": 1,
            }
        ]


def _chunk(chunk_id: str = "chunk-1") -> LegalChunk:
    return LegalChunk(
        id=chunk_id,
        document_id="civil-code",
        text="ماده ۱۰ قراردادهای خصوصی نافذ است.",
        hierarchy=LegalHierarchy(article_number="10"),
        citations=("قانون مدنی، ماده ۱۰",),
        metadata={"jurisdiction": "IR", "law_title": "قانون مدنی"},
    )


def test_openai_embedding_adapter_delegates_to_langchain() -> None:
    adapter = OpenAIEmbeddingModel(
        model_name="text-embedding-3-large",
        dimensions=2,
        embeddings=cast(OpenAIEmbeddings, StubEmbeddings()),
    )

    assert adapter.dimension == 2
    assert adapter.embed_texts(["الف", "قرارداد"]) == [[3.0, 1.0], [7.0, 1.0]]
    assert adapter.embed_query("حق") == [2.0, 1.0]


def test_openai_llm_uses_json_mode_and_langsmith_run_metadata() -> None:
    model = StubChatModel()
    adapter = OpenAILLM(
        model_name="gpt-5.6",
        chat_model=cast(ChatOpenAI, model),
    )

    result = adapter.complete(
        [
            {"role": "system", "content": "TASK=router\nReturn JSON."},
            {"role": "user", "content": "پرسش"},
        ],
        response_schema={"type": "object"},
    )

    assert result == {"intent": "legal_advice"}
    assert model.bound == {"response_format": {"type": "json_object"}}
    assert model.configs[0]["run_name"] == "persian-legal-router"
    assert model.configs[0]["metadata"]["model"] == "gpt-5.6"


def test_qdrant_adapter_upserts_precomputed_vectors_and_filters() -> None:
    repository = QdrantVectorStoreRepository(
        url="http://unused",
        collection_name="unit_legal_chunks",
        client=QdrantClient(":memory:"),
    )
    chunk = _chunk()

    repository.upsert_chunks([chunk], [[1.0, 0.0]])
    results = repository.search(
        [1.0, 0.0], filters={"jurisdiction": "IR"}, top_k=2
    )

    assert len(results) == 1
    assert results[0].chunk_id == chunk.id
    assert results[0].hierarchy.article_number == "10"
    assert results[0].citations == chunk.citations
    assert repository.search(
        [1.0, 0.0], filters={"jurisdiction": "US"}, top_k=2
    ) == []


def test_neo4j_adapter_links_chunks_and_returns_graph_context() -> None:
    graph = StubNeo4jGraph()
    repository = Neo4jGraphRepository(
        uri="bolt://unused",
        username="neo4j",
        password="password",
        graph=cast(Neo4jGraph, graph),
    )
    entity = GraphEntity(
        id="concept:contract", type="Concept", name="اصل آزادی قراردادها"
    )
    relation = GraphRelation(
        source_id="article:civil:10",
        target_id=entity.id,
        type="DEFINES",
    )

    repository.upsert_entities([entity])
    repository.upsert_relations([relation])
    repository.link_chunk(_chunk(), [entity.id])
    results = repository.expand_context(["chunk-1"], depth=1, limit=5)

    assert len(graph.calls) == 4
    assert graph.calls[2][1]["chunks"][0]["entity_ids"] == [entity.id]
    assert results[0].chunk_id == "neighbor-1"
    assert results[0].score == 0.5
    assert results[0].graph_neighbors == (entity.id,)
