"""Phase 3 RAGAS-style evaluation of generated Persian legal answers.

Metrics are provider-agnostic: LLM-judged metrics go through ``LLMPort`` (a
Persian-capable judge injected via configuration), and citation grounding is
computed deterministically. No RAGAS/pandas/vendor import leaks into the core.
"""

from legal_assistant.application.evaluation.metrics import (
    METRIC_NAMES,
    LegalAnswerEvaluator,
)
from legal_assistant.application.evaluation.service import (
    EvaluationReport,
    EvaluationService,
    SampleEvaluation,
)

__all__ = [
    "METRIC_NAMES",
    "EvaluationReport",
    "EvaluationService",
    "LegalAnswerEvaluator",
    "SampleEvaluation",
]
