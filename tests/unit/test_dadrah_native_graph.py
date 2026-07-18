from __future__ import annotations

from legal_assistant.infrastructure.graphstores.dadrah_native import (
    DadrahNativeGraphImporter,
    stable_id,
)


def test_transform_record_creates_explicit_question_answer_lawyer_and_tag() -> None:
    record = {
        "request_id": "800001",
        "page_url": "https://example.test/question/800001",
        "fetched_at": "2026-07-17T20:54:00+00:00",
        "question": {
            "title": "مطالبه وجه",
            "text": "چه اقدامی انجام دهم؟",
            "tags": [{"name": "مطالبه وجه", "url": "https://example.test/tag"}],
        },
        "answers": [{
            "number": 7,
            "text": "دادخواست ثبت کنید.",
            "lawyer": {"name": "وکیل نمونه", "city": "تهران", "profile_url": "https://example.test/lawyer"},
        }],
    }

    transformed = DadrahNativeGraphImporter.transform_record(
        record, source_file="dadrah.jsonl", source_line=1
    )

    assert transformed is not None
    assert transformed["question"]["id"] == "question:800001"
    assert transformed["answers"][0]["id"] == "answer:800001:1"
    assert transformed["answers"][0]["answer_number"] == "7"
    assert transformed["tags"][0]["id"] == stable_id("tag", "مطالبه وجه")
    assert transformed["answers"][0]["lawyer"]["id"] == stable_id(
        "lawyer", "https://example.test/lawyer"
    )


def test_transform_record_skips_not_found() -> None:
    assert DadrahNativeGraphImporter.transform_record(
        {"status": "not_found"}, source_file="dadrah.jsonl", source_line=2
    ) is None
