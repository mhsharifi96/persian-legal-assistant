import pytest

from legal_assistant.application.services.graph_extraction import GraphExtractionService
from legal_assistant.domain.errors import GraphExtractionError
from legal_assistant.domain.models import LegalChunk, LegalHierarchy
from legal_assistant.infrastructure.fakes import FakeLLM


def _chunk() -> LegalChunk:
    return LegalChunk(
        id="chunk-1",
        document_id="law",
        text="ماده ۱۰ - متن نمونه",
        hierarchy=LegalHierarchy(article_number="10"),
        citations=("قانون نمونه، ماده 10",),
        metadata={},
    )


def test_graph_extraction_validates_structured_output():
    llm = FakeLLM(
        [
            {
                "entities": [
                    {
                        "id": "article:law:10",
                        "type": "Article",
                        "name": "ماده ۱۰ قانون نمونه",
                        "properties": {},
                    }
                ],
                "relationships": [],
            }
        ]
    )

    extraction = GraphExtractionService(llm).extract(_chunk())

    assert extraction.entities[0].type == "Article"
    assert extraction.entities[0].name == "ماده ۱۰ قانون نمونه"


def test_graph_extraction_retries_once_for_repair():
    llm = FakeLLM(
        [
            {"entities": [{"id": "x", "type": "FreeForm", "name": "bad"}]},
            {"entities": [], "relationships": []},
        ]
    )

    extraction = GraphExtractionService(llm).extract(_chunk())

    assert extraction.entities == ()
    assert len(llm.messages) == 2


def test_graph_extraction_raises_after_failed_repair():
    llm = FakeLLM(
        [
            {"entities": [{"id": "x", "type": "FreeForm", "name": "bad"}]},
            {"entities": [{"id": "x", "type": "FreeForm", "name": "bad"}]},
        ]
    )

    with pytest.raises(GraphExtractionError):
        GraphExtractionService(llm).extract(_chunk())
