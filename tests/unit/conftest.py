from __future__ import annotations

import pytest

from legal_assistant.domain.models import (
    GraphEntity,
    GraphExtraction,
    LegalChunk,
    LegalDocument,
    LegalHierarchy,
)
from legal_assistant.infrastructure.fakes import (
    FakeDocumentParser,
    FakeEmbeddingModel,
    FakeGraphExtractor,
    FakeLLM,
    InMemoryGraphRepository,
    InMemoryVectorStoreRepository,
)

SAMPLE_LEGAL_TEXT = (
    "کتاب اول\n"
    "باب اول\n"
    "فصل دوم\n"
    "ماده ۱۰ - قراردادهای خصوصی نسبت به کسانی که آن را منعقد نموده‌اند نافذ است.\n"
    "تبصره ۱ - این تبصره برای نمونه است.\n"
    "تبصره ۲ - تبصره دوم باید جداگانه حفظ شود.\n"
    "ماده ۱۱: اموال بر دو قسم است."
)

SAMPLE_ARTICLE_TEXT = "ماده ۱ - متن ماده\nتبصره ۱ - متن تبصره"


@pytest.fixture
def sample_document() -> LegalDocument:
    return LegalDocument(
        id="civil-code",
        title="قانون مدنی",
        source_uri="file:///laws/civil-code.txt",
        jurisdiction="IR",
        document_type="law",
        text=SAMPLE_LEGAL_TEXT,
        parser_name="fake",
        metadata={"page_start": 1, "page_end": 2},
    )


@pytest.fixture
def sample_chunk() -> LegalChunk:
    return LegalChunk(
        id="chunk-1",
        document_id="law",
        text="ماده ۱۰ - متن نمونه",
        hierarchy=LegalHierarchy(article_number="10"),
        citations=("قانون نمونه، ماده 10",),
        metadata={},
    )


@pytest.fixture
def sample_single_article_document() -> LegalDocument:
    return LegalDocument(
        id="law",
        title="قانون نمونه",
        source_uri="file:///law.txt",
        jurisdiction="IR",
        document_type="law",
        text=SAMPLE_ARTICLE_TEXT,
    )


@pytest.fixture
def sample_graph_entity() -> GraphEntity:
    return GraphEntity(
        id="article:law:1",
        type="Article",
        name="ماده ۱",
    )


@pytest.fixture
def sample_graph_extraction(sample_graph_entity: GraphEntity) -> GraphExtraction:
    return GraphExtraction(entities=(sample_graph_entity,))


@pytest.fixture
def fake_ports():
    return {
        "parser": FakeDocumentParser([]),
        "embeddings": FakeEmbeddingModel(),
        "vector_store": InMemoryVectorStoreRepository(),
        "graph_store": InMemoryGraphRepository(),
        "llm": FakeLLM([]),
        "graph_extractor": FakeGraphExtractor(),
    }
