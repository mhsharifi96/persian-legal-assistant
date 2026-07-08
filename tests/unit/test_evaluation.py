from __future__ import annotations

import json
from pathlib import Path

from legal_assistant.application.evaluation.metrics import (
    LegalAnswerEvaluator,
    citation_grounding_score,
)
from legal_assistant.application.evaluation.service import EvaluationService
from legal_assistant.config.bootstrap import build_evaluation_service
from legal_assistant.config.settings import Settings
from legal_assistant.domain.models import EvaluationRecord
from legal_assistant.infrastructure.fakes import (
    InMemoryEvaluationRepository,
    TaggedFakeLLM,
)
from legal_assistant.infrastructure.repositories.jsonl import (
    JsonlEvaluationRepository,
    JsonlLawyerRepository,
)


def _record(
    question: str,
    *,
    ground_truth: str = "",
    contexts: tuple[str, ...] = (),
    citations: tuple[str, ...] = (),
) -> EvaluationRecord:
    return EvaluationRecord(
        question=question,
        answer=f"پاسخ {question}",
        contexts=contexts,
        ground_truth=ground_truth,
        citations=citations,
        metadata={"domain": "contract", "jurisdiction": "IR"},
    )


def test_citation_grounding_matches_and_penalizes_uncited() -> None:
    grounded = _record(
        "q",
        ground_truth="مطابق قانون مدنی، ماده ۱۰ توافق نافذ است.",
        citations=("قانون مدنی، ماده ۱۰",),
    )
    score, _ = citation_grounding_score(grounded)
    assert score == 1.0

    uncited = _record("q")
    score, reason = citation_grounding_score(uncited)
    assert score == 0.0
    assert "استناد" in reason


def test_evaluation_report_aggregates_and_ranks_worst() -> None:
    records = [
        _record(
            "q1",
            ground_truth="قانون مدنی، ماده ۱۰",
            citations=("قانون مدنی، ماده ۱۰",),
        ),
        _record("q2"),  # no citations -> grounding 0.0
    ]
    llm = TaggedFakeLLM(
        scripts={
            "eval_faithfulness": [{"score": 0.2}, {"score": 0.8}],
            "eval_context_precision": [{"score": 0.4}, {"score": 1.0}],
            "eval_answer_relevancy": [{"score": 1.0}, {"score": 1.0}],
            "eval_jurisdiction": [{"score": 1.0}, {"score": 1.0}],
        }
    )
    service = EvaluationService(LegalAnswerEvaluator(llm), failure_threshold=0.5)

    report = service.evaluate(records)

    faith = report.aggregates["faithfulness"]
    assert round(faith.mean, 4) == 0.5
    assert faith.median == 0.5
    assert faith.failures == 1  # 0.2 < 0.5
    assert report.aggregates["citation_grounding"].mean == 0.5
    # worst-by faithfulness lists q1 (0.2) first
    worst_faith = report.worst_examples["faithfulness"]
    assert worst_faith[0].record.question == "q1"
    assert "faithfulness" in report.persian_summary
    assert "ارزیابی 2 نمونه" in report.persian_summary


def test_report_to_records_has_metric_columns() -> None:
    records = [_record("q1", citations=("x",))]
    service = EvaluationService(LegalAnswerEvaluator(TaggedFakeLLM()))

    report = service.evaluate(records)
    rows = report.to_records()

    assert rows[0]["question"] == "q1"
    assert rows[0]["meta_domain"] == "contract"
    for metric in report.metric_names:
        assert metric in rows[0]
    # metric column must not be clobbered by a metadata column of the same name
    assert rows[0]["jurisdiction"] == report.samples[0].scores["jurisdiction"]


def test_evaluate_repository_uses_port() -> None:
    repo = InMemoryEvaluationRepository([_record("q1"), _record("q2")])
    service = EvaluationService(LegalAnswerEvaluator(TaggedFakeLLM()))

    report = service.evaluate_repository(repo)

    assert len(report.samples) == 2


def test_bootstrap_evaluation_service_smoke() -> None:
    service = build_evaluation_service(Settings())
    report = service.evaluate([_record("q", citations=("x",))])

    # Default fake judge returns 1.0 for every eval_* metric.
    assert report.aggregates["faithfulness"].mean == 1.0


def test_jsonl_repositories_load_and_normalize(tmp_path: Path) -> None:
    lawyers_path = tmp_path / "lawyers.jsonl"
    lawyers_path.write_text(
        json.dumps(
            {
                "lawyer_id": "l1",
                "full_name": "وکیل اول",
                "specialties": "خانواده، ملکی",
                "location": "تهران",
                "success_rate": 82,  # percent -> normalized to 0.82
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    lawyers = JsonlLawyerRepository(lawyers_path).list_lawyers()
    assert lawyers[0].specialties == ("خانواده", "ملکی")
    assert lawyers[0].success_rate == 0.82

    eval_path = tmp_path / "eval.jsonl"
    eval_path.write_text(
        json.dumps(
            {
                "question": "پرسش",
                "answer": "پاسخ",
                "contexts": ["ماده ۱۰"],
                "ground_truth": "خلاصه",
                "citations": ["قانون مدنی، ماده ۱۰"],
                "metadata": {"domain": "contract"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    records = JsonlEvaluationRepository(eval_path).load_records()
    assert records[0].contexts == ("ماده ۱۰",)
    assert records[0].citations == ("قانون مدنی، ماده ۱۰",)
