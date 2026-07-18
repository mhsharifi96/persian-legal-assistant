import pytest

from legal_assistant.config.bootstrap import build_document_parser, build_hybrid_retriever
from legal_assistant.infrastructure.parsers import LocalFileDocumentParser
from legal_assistant.config.settings import Settings


def test_build_hybrid_retriever_uses_fake_providers_by_default() -> None:
    retriever = build_hybrid_retriever(Settings())

    assert retriever is not None


def test_build_hybrid_retriever_raises_for_unknown_embedding_provider() -> None:
    with pytest.raises(ValueError, match="embedding provider"):
        build_hybrid_retriever(Settings(embedding_provider="unknown"))


def test_build_hybrid_retriever_raises_for_unknown_vector_store_provider() -> None:
    with pytest.raises(ValueError, match="vector store provider"):
        build_hybrid_retriever(Settings(vectorstore_provider="unknown"))


def test_build_local_document_parser() -> None:
    parser = build_document_parser(Settings(parser_provider="local"))

    assert isinstance(parser, LocalFileDocumentParser)
