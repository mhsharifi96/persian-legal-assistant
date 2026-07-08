from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Sequence

from legal_assistant.application.evaluation.metrics import (
    METRIC_NAMES,
    LegalAnswerEvaluator,
)
from legal_assistant.application.ports import EvaluationRepository
from legal_assistant.domain.models import EvaluationRecord


@dataclass(frozen=True)
class SampleEvaluation:
    record: EvaluationRecord
    scores: dict[str, float]
    reasons: dict[str, str]


@dataclass(frozen=True)
class MetricAggregate:
    mean: float
    median: float
    minimum: float
    failures: int


@dataclass(frozen=True)
class EvaluationReport:
    samples: tuple[SampleEvaluation, ...]
    metric_names: tuple[str, ...]
    aggregates: dict[str, MetricAggregate]
    worst_examples: dict[str, tuple[SampleEvaluation, ...]]
    persian_summary: str
    failure_threshold: float = 0.5

    def to_records(self) -> list[dict[str, Any]]:
        """Flat per-sample rows — feed directly to ``pandas.DataFrame(...)`` in a
        reporting adapter without the core depending on pandas."""
        rows: list[dict[str, Any]] = []
        for sample in self.samples:
            # Prefix metadata columns so they never collide with a metric name
            # (e.g. the ``jurisdiction`` aspect-critic metric vs. metadata).
            row: dict[str, Any] = {
                "question": sample.record.question,
                "meta_domain": sample.record.metadata.get("domain"),
                "meta_jurisdiction": sample.record.metadata.get("jurisdiction"),
            }
            for metric in self.metric_names:
                row[metric] = sample.scores.get(metric)
            rows.append(row)
        return rows


class EvaluationService:
    def __init__(
        self,
        evaluator: LegalAnswerEvaluator,
        *,
        failure_threshold: float = 0.5,
        worst_k: int = 3,
    ) -> None:
        self._evaluator = evaluator
        self._failure_threshold = failure_threshold
        self._worst_k = worst_k

    def evaluate_repository(self, repository: EvaluationRepository) -> EvaluationReport:
        return self.evaluate(repository.load_records())

    def evaluate(self, records: Sequence[EvaluationRecord]) -> EvaluationReport:
        samples = [
            SampleEvaluation(record, *self._evaluator.evaluate(record))
            for record in records
        ]
        metric_names = tuple(
            name
            for name in METRIC_NAMES
            if any(name in sample.scores for sample in samples)
        )
        aggregates = self._aggregate(samples, metric_names)
        worst = self._worst_examples(samples, metric_names)
        summary = self._summary(samples, metric_names, aggregates)
        return EvaluationReport(
            samples=tuple(samples),
            metric_names=metric_names,
            aggregates=aggregates,
            worst_examples=worst,
            persian_summary=summary,
            failure_threshold=self._failure_threshold,
        )

    def _aggregate(
        self,
        samples: Sequence[SampleEvaluation],
        metric_names: Sequence[str],
    ) -> dict[str, MetricAggregate]:
        aggregates: dict[str, MetricAggregate] = {}
        for metric in metric_names:
            values = [
                sample.scores[metric]
                for sample in samples
                if metric in sample.scores
            ]
            if not values:
                continue
            aggregates[metric] = MetricAggregate(
                mean=statistics.fmean(values),
                median=statistics.median(values),
                minimum=min(values),
                failures=sum(1 for v in values if v < self._failure_threshold),
            )
        return aggregates

    def _worst_examples(
        self,
        samples: Sequence[SampleEvaluation],
        metric_names: Sequence[str],
    ) -> dict[str, tuple[SampleEvaluation, ...]]:
        # Contract highlights faithfulness and context precision; include any
        # of them that were actually scored.
        focus = [m for m in ("faithfulness", "context_precision") if m in metric_names]
        worst: dict[str, tuple[SampleEvaluation, ...]] = {}
        for metric in focus:
            ranked = sorted(samples, key=lambda s: s.scores.get(metric, 1.0))
            worst[metric] = tuple(ranked[: self._worst_k])
        return worst

    def _summary(
        self,
        samples: Sequence[SampleEvaluation],
        metric_names: Sequence[str],
        aggregates: dict[str, MetricAggregate],
    ) -> str:
        if not samples:
            return "هیچ نمونه‌ای برای ارزیابی وجود ندارد."
        parts = [f"ارزیابی {len(samples)} نمونه:"]
        for metric in metric_names:
            agg = aggregates.get(metric)
            if agg is None:
                continue
            parts.append(
                f"{metric}: میانگین {agg.mean:.2f}، میانه {agg.median:.2f}، "
                f"تعداد ناموفق {agg.failures}"
            )
        return " | ".join(parts)
