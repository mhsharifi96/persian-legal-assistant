# Phase 3 Evaluation and Recommendation Contracts

## Recommendation Ports

```python
class LawyerRepository(Protocol):
    def list_lawyers(self, *, filters: dict | None = None) -> list[LawyerProfile]: ...

class LawyerRecommendationService:
    def __init__(
        self,
        lawyers: LawyerRepository,
        embeddings: EmbeddingModelPort,
        settings: RecommendationSettings,
    ): ...
```

## Lawyer Profile

Recommended profile:

```python
LawyerProfile(
    lawyer_id: str,
    full_name: str,
    specialties: str | list[str],
    location: str,
    success_rate: float,
    metadata: dict = {},
)
```

`success_rate` should be normalized to `0..1`. If source data uses percentages, normalize in the repository or a mapper.

## Recommendation Result

```python
LawyerRecommendation(
    lawyer_id: str,
    full_name: str,
    score: float,
    semantic_score: float,
    success_score: float,
    location_score: float,
    rationale: str,
)
```

The rationale should be concise Persian text explaining specialty match, location match, and success-rate contribution.

## Evaluation Dataset

Use this canonical record:

```json
{
  "question": "پرسش حقوقی کاربر",
  "answer": "پاسخ تولیدشده سیستم",
  "contexts": ["متن ماده قانونی یا رای مرتبط"],
  "ground_truth": "پاسخ مرجع یا خلاصه حقوقی تاییدشده",
  "citations": ["قانون مدنی، ماده ۱۰"],
  "metadata": {
    "domain": "contract",
    "jurisdiction": "IR",
    "source": "golden_set_v1"
  }
}
```

## Metrics

Use:

- context precision: آیا زمینه بازیابی‌شده واقعا مرتبط است؟
- faithfulness: آیا پاسخ فقط از context پشتیبانی می‌شود؟
- answer relevancy: آیا پاسخ به سؤال کاربر پاسخ می‌دهد؟
- legal citation grounding aspect critic: آیا گزاره‌های حقوقی مهم citation دارند؟
- jurisdiction aspect critic: آیا پاسخ با حقوق ایران و زمینه داده‌شده سازگار است؟

## Judge LLM

Use a Persian-capable judge LLM through configuration. The implementation may use OpenAI or a local model, but evaluation orchestration must not hard-code the provider.

Expected judge instruction:

```text
Evaluate the Persian legal answer only against the provided context and ground truth.
Penalize unsupported legal obligations, deadlines, penalties, and advice.
Do not reward fluent but uncited answers.
```

## Reporting

Return:

- per-sample scores as a Pandas DataFrame;
- aggregate mean, median, and failure counts;
- worst examples by faithfulness and context precision;
- short Persian summary for thesis reporting.

## Test Strategy

- Unit-test scoring math with fixed vectors.
- Unit-test normalization and tie-breaking.
- Use a tiny evaluation fixture with 2 to 5 examples.
- Mock judge LLM calls in unit tests.
- Keep live RAGAS or LLM evaluation behind an integration marker.
