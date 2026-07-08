from __future__ import annotations

import json
from typing import Any, Sequence

from legal_assistant.application.ports import LLMPort
from legal_assistant.domain.models import EvaluationRecord

# Metric order is stable for reporting/columns.
METRIC_NAMES: tuple[str, ...] = (
    "context_precision",
    "faithfulness",
    "answer_relevancy",
    "citation_grounding",
    "jurisdiction",
)

# LLM judge task tags (see TaggedFakeLLM for the fake counterpart).
_LLM_METRIC_TAGS: dict[str, str] = {
    "context_precision": "eval_context_precision",
    "faithfulness": "eval_faithfulness",
    "answer_relevancy": "eval_answer_relevancy",
    "jurisdiction": "eval_jurisdiction",
}

_METRIC_INSTRUCTIONS: dict[str, str] = {
    "context_precision": (
        "Judge context precision: is the retrieved context actually relevant to "
        "the question? Reply as JSON with keys score (0..1) and reason."
    ),
    "faithfulness": (
        "Judge faithfulness: is the answer supported ONLY by the provided context "
        "and ground truth? Penalize unsupported legal obligations, deadlines, "
        "penalties, and advice. Reply as JSON with keys score (0..1) and reason."
    ),
    "answer_relevancy": (
        "Judge answer relevancy: does the answer address the user's question? "
        "Reply as JSON with keys score (0..1) and reason."
    ),
    "jurisdiction": (
        "Aspect critic: is the answer consistent with Iranian law and the given "
        "context/jurisdiction? Reply as JSON with keys score (0..1) and reason."
    ),
}

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_JUDGE_PREAMBLE = (
    "You are a strict Persian legal answer evaluator. Evaluate only against the "
    "provided context and ground truth. Do not reward fluent but uncited answers."
)


def _load_json(response: str | dict[str, Any]) -> dict[str, Any]:
    data = json.loads(response) if isinstance(response, str) else response
    if not isinstance(data, dict):
        raise ValueError("Judge response must be a JSON object")
    return data


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize(text: str) -> str:
    return " ".join(text.translate(PERSIAN_DIGITS).split()).casefold()


def citation_grounding_score(record: EvaluationRecord) -> tuple[float, str]:
    """Deterministic critic: are the answer's citations actually present in the
    retrieved context (or ground truth)? Uncited answers score 0."""
    if not record.citations:
        return 0.0, "پاسخ فاقد استناد است."
    haystack = _normalize(" \n ".join((*record.contexts, record.ground_truth)))
    matched = sum(
        1 for citation in record.citations if _normalize(citation) in haystack
    )
    score = matched / len(record.citations)
    reason = f"{matched} از {len(record.citations)} استناد در زمینه یافت شد."
    return score, reason


class LegalAnswerEvaluator:
    """Scores one :class:`EvaluationRecord` across all metrics.

    LLM-judged metrics use the injected ``LLMPort``; citation grounding is
    deterministic and needs no LLM call.
    """

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    def evaluate(
        self, record: EvaluationRecord
    ) -> tuple[dict[str, float], dict[str, str]]:
        scores: dict[str, float] = {}
        reasons: dict[str, str] = {}

        for metric, tag in _LLM_METRIC_TAGS.items():
            score, reason = self._llm_metric(metric, tag, record)
            scores[metric] = score
            reasons[metric] = reason

        grounding_score, grounding_reason = citation_grounding_score(record)
        scores["citation_grounding"] = grounding_score
        reasons["citation_grounding"] = grounding_reason
        return scores, reasons

    def _llm_metric(
        self, metric: str, tag: str, record: EvaluationRecord
    ) -> tuple[float, str]:
        payload = {
            "question": record.question,
            "answer": record.answer,
            "contexts": list(record.contexts),
            "ground_truth": record.ground_truth,
            "citations": list(record.citations),
            "metadata": record.metadata,
        }
        response = self._llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        f"TASK={tag}\n{_JUDGE_PREAMBLE}\n{_METRIC_INSTRUCTIONS[metric]}"
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_schema={"type": "object"},
        )
        data = _load_json(response)
        score = _clamp01(float(data.get("score", 0.0)))
        reason = str(data.get("reason", ""))
        return score, reason


def metric_columns(scores: Sequence[dict[str, float]]) -> tuple[str, ...]:
    """Stable metric column order, restricted to what was actually scored."""
    present = {name for row in scores for name in row}
    return tuple(name for name in METRIC_NAMES if name in present)
