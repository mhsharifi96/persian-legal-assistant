from __future__ import annotations

from legal_assistant.application.services.hybrid_retriever import HybridRetriever
from legal_assistant.infrastructure.fakes import (
    FakeEmbeddingModel,
    InMemoryGraphRepository,
    InMemoryVectorStoreRepository,
)
from legal_assistant.config.settings import Settings


def build_fake_hybrid_retriever(settings: Settings) -> HybridRetriever:
    if settings.embedding_provider != "fake":
        raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")
    if settings.vectorstore_provider != "memory":
        raise ValueError(f"Unsupported vector store provider: {settings.vectorstore_provider}")
    if settings.graphstore_provider != "memory":
        raise ValueError(f"Unsupported graph store provider: {settings.graphstore_provider}")

    return HybridRetriever(
        embeddings=FakeEmbeddingModel(),
        vector_store=InMemoryVectorStoreRepository(),
        graph_store=InMemoryGraphRepository(),
        graph_depth=settings.graph_depth,
    )
