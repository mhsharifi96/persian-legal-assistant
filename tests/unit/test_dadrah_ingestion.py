from __future__ import annotations

import json
from pathlib import Path

from legal_assistant.application.services.ingestion import DocumentIngestionService
from legal_assistant.infrastructure.chunkers import DadrahConsultationChunker
from legal_assistant.infrastructure.graphstores.dadrah_extractor import (
    DadrahGraphExtractor,
)
from legal_assistant.infrastructure.parsers import DadrahJsonlParser
from legal_assistant.infrastructure.fakes import (
    FakeEmbeddingModel,
    InMemoryVectorStoreRepository,
)


def _write_dataset(path: Path) -> None:
    records = [
        {
            "request_id": "800001",
            "fetched_at": "2026-07-17T20:54:00+00:00",
            "page_url": "https://www.dadrah.ir/consulting-paper.php?requestID=800001",
            "question": {
                "title": "مشاوره حقوقی رایگان - مطالبه وجه",
                "text": "برای مطالبه وجه چه کار کنم؟",
                "tags": [{"name": "مطالبه وجه", "url": "https://example.test/tag"}],
            },
            "answers": [
                {
                    "number": 1,
                    "text": "دادخواست مطالبه وجه ثبت کنید.",
                    "date": "۱۴۰۴/۱/۱",
                    "time": "۱۰:۰۰:۰۰",
                    "lawyer": {
                        "name": "وکیل نمونه",
                        "city": "تهران",
                        "profile_url": "https://example.test/lawyer",
                    },
                }
            ],
        },
        {
            "request_id": "800002",
            "status": "not_found",
            "question": None,
            "answers": [],
        },
    ]
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
        encoding="utf-8",
    )


def test_dadrah_parser_and_chunker_preserve_provenance(tmp_path: Path) -> None:
    source = tmp_path / "dadrah.jsonl"
    _write_dataset(source)

    documents = DadrahJsonlParser().parse(str(source))
    chunks = DadrahConsultationChunker().chunk(documents[0])

    assert len(documents) == 1
    assert documents[0].id == "dadrah:800001"
    assert documents[0].document_type == "legal_consultation"
    assert [chunk.metadata["content_role"] for chunk in chunks] == [
        "question",
        "answer",
    ]
    assert chunks[1].metadata["lawyer_name"] == "وکیل نمونه"
    assert "پرسش:" in chunks[1].text
    assert chunks[1].citations == (documents[0].source_uri,)


def test_dadrah_graph_extractor_builds_tags_and_lawyer_links(tmp_path: Path) -> None:
    source = tmp_path / "dadrah.jsonl"
    _write_dataset(source)
    document = DadrahJsonlParser().parse(str(source))[0]
    question, answer = DadrahConsultationChunker().chunk(document)
    extractor = DadrahGraphExtractor()

    question_graph = extractor.extract(question)
    answer_graph = extractor.extract(answer)

    assert {entity.type for entity in question_graph.entities} == {
        "Consultation",
        "Topic",
    }
    assert [relation.type for relation in question_graph.relations] == ["HAS_TAG"]
    assert {entity.type for entity in answer_graph.entities} == {
        "Consultation",
        "Lawyer",
    }
    assert [relation.type for relation in answer_graph.relations] == ["ANSWERED_BY"]


def test_dadrah_vector_index_can_include_questions_only(tmp_path: Path) -> None:
    source = tmp_path / "dadrah.jsonl"
    _write_dataset(source)
    vector_store = InMemoryVectorStoreRepository()
    service = DocumentIngestionService(
        parser=DadrahJsonlParser(),
        chunker=DadrahConsultationChunker(),
        embeddings=FakeEmbeddingModel(),
        vector_store=vector_store,
        vector_chunk_filter=lambda chunk: chunk.metadata.get("content_role")
        == "question",
    )

    result = service.ingest(str(source))

    assert result.chunk_count == 2
    assert len(vector_store.chunks) == 1
    assert next(iter(vector_store.chunks.values())).metadata["content_role"] == "question"
