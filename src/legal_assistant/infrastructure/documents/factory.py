from __future__ import annotations

from typing import cast

from django.conf import settings

from legal_assistant.application.document_ingestion import DocumentIngestionService
from legal_assistant.application.document_ingestion import EmbeddingProvider
from legal_assistant.infrastructure.documents.embeddings import (
    HashingEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from legal_assistant.infrastructure.documents.pdf import PyPdfTextExtractor
from legal_assistant.infrastructure.documents.qdrant import QdrantDocumentVectorStore
from legal_assistant.infrastructure.documents.repository import DjangoDocumentRepository


def build_document_ingestion_service() -> DocumentIngestionService:
    provider = cast(str, settings.EMBEDDING_PROVIDER).casefold()
    embedding_builders = {
        "hashing": lambda: HashingEmbeddingProvider(
            dimension=cast(int, settings.EMBEDDING_DIMENSIONS)
        ),
        "openai": lambda: OpenAIEmbeddingProvider(
            model_name=cast(str, settings.EMBEDDING_MODEL_NAME),
            dimension=cast(int, settings.EMBEDDING_DIMENSIONS),
            api_key=cast(str, settings.OPENAI_API_KEY),
            base_url=cast(str | None, settings.OPENAI_API_BASE),
            batch_size=cast(int, settings.EMBEDDING_BATCH_SIZE),
        ),
    }
    try:
        embeddings: EmbeddingProvider = embedding_builders[provider]()
    except KeyError as exc:
        raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {provider}") from exc
    return DocumentIngestionService(
        DjangoDocumentRepository(),
        PyPdfTextExtractor(),
        embeddings,
        QdrantDocumentVectorStore(
            url=cast(str, settings.QDRANT_URL),
            collection_name=cast(str, settings.QDRANT_COLLECTION_NAME),
            api_key=cast(str, settings.QDRANT_API_KEY),
        ),
        max_chunk_chars=cast(int, settings.DOCUMENT_CHUNK_CHARS),
        chunk_overlap_chars=cast(int, settings.DOCUMENT_CHUNK_OVERLAP_CHARS),
    )
