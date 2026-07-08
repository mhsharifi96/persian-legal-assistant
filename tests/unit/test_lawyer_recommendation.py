from __future__ import annotations

from typing import Sequence

from legal_assistant.application.services.lawyer_recommendation import (
    LawyerRecommendationService,
    RecommendationSettings,
)
from legal_assistant.domain.models import LawyerProfile
from legal_assistant.infrastructure.fakes import (
    FakeEmbeddingModel,
    InMemoryLawyerRepository,
)


class FixedEmbeddingModel:
    """Maps known texts to fixed vectors so scoring math is deterministic."""

    def __init__(self, vectors: dict[str, list[float]], dimension: int = 3) -> None:
        self._vectors = vectors
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        for key, vector in self._vectors.items():
            if key in text:
                return vector
        return [0.0] * self._dimension


def _profile(
    lawyer_id: str,
    specialties: tuple[str, ...],
    location: str,
    success_rate: float,
) -> LawyerProfile:
    return LawyerProfile(
        lawyer_id=lawyer_id,
        full_name=f"وکیل {lawyer_id}",
        specialties=specialties,
        location=location,
        success_rate=success_rate,
    )


def test_semantic_success_location_weighted_scoring() -> None:
    profiles = [
        _profile("a", ("خانواده",), "تهران", 0.8),
        _profile("b", ("کیفری",), "شیراز", 0.9),
    ]
    embeddings = FixedEmbeddingModel(
        {
            "طلاق": [1.0, 0.0, 0.0],
            "خانواده": [1.0, 0.0, 0.0],  # aligned with query -> semantic 1.0
            "کیفری": [0.0, 1.0, 0.0],  # orthogonal -> semantic 0.0
        }
    )
    service = LawyerRecommendationService(
        InMemoryLawyerRepository(profiles),
        embeddings,
        RecommendationSettings(
            semantic_weight=0.5, success_weight=0.3, location_weight=0.2
        ),
    )

    results = service.recommend("پرونده طلاق", location="تهران")

    assert [r.lawyer_id for r in results] == ["a", "b"]
    top = results[0]
    # 0.5*1.0 + 0.3*0.8 + 0.2*1.0 = 0.94
    assert round(top.score, 4) == 0.94
    assert top.semantic_score == 1.0
    assert top.location_score == 1.0
    assert top.success_score == 0.8
    # b: 0.5*0 + 0.3*0.9 + 0.2*0 = 0.27
    assert round(results[1].score, 4) == 0.27
    assert "خانواده" in top.rationale


def test_location_mismatch_scores_zero_location() -> None:
    profiles = [_profile("a", ("خانواده",), "تهران", 0.5)]
    embeddings = FakeEmbeddingModel()
    service = LawyerRecommendationService(InMemoryLawyerRepository(profiles), embeddings)

    results = service.recommend("پرسش", location="اصفهان")

    assert results[0].location_score == 0.0
    assert "بدون مطابقت محل" in results[0].rationale


def test_persian_digit_location_normalization() -> None:
    profiles = [_profile("a", ("ملکی",), "منطقه ۱۲", 0.5)]
    service = LawyerRecommendationService(
        InMemoryLawyerRepository(profiles), FakeEmbeddingModel()
    )

    results = service.recommend("پرسش", location="منطقه 12")  # ASCII digits

    assert results[0].location_score == 1.0


def test_tie_breaking_prefers_higher_success_then_id() -> None:
    # Both have identical semantic (empty query vector) and no location match,
    # so success_rate breaks the tie, then lawyer_id.
    profiles = [
        _profile("z", ("الف",), "تهران", 0.6),
        _profile("a", ("الف",), "تهران", 0.6),
        _profile("m", ("الف",), "تهران", 0.9),
    ]
    service = LawyerRecommendationService(
        InMemoryLawyerRepository(profiles), FakeEmbeddingModel()
    )

    results = service.recommend("چیز")

    assert [r.lawyer_id for r in results] == ["m", "a", "z"]


def test_top_n_limits_results() -> None:
    profiles = [_profile(str(i), ("الف",), "تهران", 0.5) for i in range(10)]
    service = LawyerRecommendationService(
        InMemoryLawyerRepository(profiles), FakeEmbeddingModel()
    )

    assert len(service.recommend("q", top_n=3)) == 3


def test_empty_repository_returns_empty() -> None:
    service = LawyerRecommendationService(
        InMemoryLawyerRepository([]), FakeEmbeddingModel()
    )

    assert service.recommend("q") == []


def test_specialty_filter_is_applied() -> None:
    profiles = [
        _profile("a", ("خانواده",), "تهران", 0.5),
        _profile("b", ("کیفری",), "تهران", 0.5),
    ]
    service = LawyerRecommendationService(
        InMemoryLawyerRepository(profiles), FakeEmbeddingModel()
    )

    results = service.recommend("q", filters={"specialty": "کیفری"})

    assert [r.lawyer_id for r in results] == ["b"]
