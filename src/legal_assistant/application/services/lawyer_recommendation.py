from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

from legal_assistant.application.ports import EmbeddingModelPort, LawyerRepository
from legal_assistant.domain.models import LawyerProfile, LawyerRecommendation

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


@dataclass(frozen=True)
class RecommendationSettings:
    """Transparent weighted-score configuration. A practical approximation of
    multi-objective ranking — not a full AGE-MOEA implementation."""

    semantic_weight: float = 0.5
    success_weight: float = 0.3
    location_weight: float = 0.2
    top_n: int = 5


def _normalize_location(value: str) -> str:
    return " ".join(value.translate(PERSIAN_DIGITS).split()).casefold()


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(
        sum(y * y for y in right)
    )
    if denominator == 0:
        return 0.0
    return sum(x * y for x, y in zip(left, right, strict=False)) / denominator


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _profile_text(profile: LawyerProfile) -> str:
    return "، ".join((*profile.specialties, profile.full_name))


class LawyerRecommendationService:
    """Analyze intent -> embed -> fetch lawyers -> score -> return top N.

    Depends only on ``LawyerRepository`` and ``EmbeddingModelPort`` so the data
    source (in-memory/JSONL/SQL/API) and embedding model stay replaceable.
    """

    def __init__(
        self,
        lawyers: LawyerRepository,
        embeddings: EmbeddingModelPort,
        settings: RecommendationSettings | None = None,
    ) -> None:
        self._lawyers = lawyers
        self._embeddings = embeddings
        self._settings = settings or RecommendationSettings()

    def recommend(
        self,
        query: str,
        *,
        location: str | None = None,
        top_n: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[LawyerRecommendation]:
        profiles = self._lawyers.list_lawyers(filters=filters)
        if not profiles:
            return []

        query_vector = self._embeddings.embed_query(query)
        profile_vectors = self._embeddings.embed_texts(
            [_profile_text(profile) for profile in profiles]
        )
        normalized_location = (
            _normalize_location(location) if location else None
        )

        settings = self._settings
        recommendations: list[LawyerRecommendation] = []
        for profile, vector in zip(profiles, profile_vectors, strict=True):
            semantic_score = _clamp01(_cosine(query_vector, vector))
            success_score = _clamp01(profile.success_rate)
            location_score = (
                1.0
                if normalized_location is not None
                and _normalize_location(profile.location) == normalized_location
                else 0.0
            )
            final_score = (
                settings.semantic_weight * semantic_score
                + settings.success_weight * success_score
                + settings.location_weight * location_score
            )
            recommendations.append(
                LawyerRecommendation(
                    lawyer_id=profile.lawyer_id,
                    full_name=profile.full_name,
                    score=final_score,
                    semantic_score=semantic_score,
                    success_score=success_score,
                    location_score=location_score,
                    rationale=self._rationale(
                        profile, semantic_score, success_score, location_score
                    ),
                )
            )

        # Deterministic ordering: score desc, then success desc, then id.
        recommendations.sort(
            key=lambda rec: (-rec.score, -rec.success_score, rec.lawyer_id)
        )
        limit = top_n if top_n is not None else settings.top_n
        return recommendations[:limit]

    def _rationale(
        self,
        profile: LawyerProfile,
        semantic_score: float,
        success_score: float,
        location_score: float,
    ) -> str:
        specialties = "، ".join(profile.specialties) or "نامشخص"
        location_note = (
            f"محل ({profile.location}) با درخواست مطابقت دارد"
            if location_score > 0
            else "بدون مطابقت محل"
        )
        return (
            f"تخصص‌ها: {specialties} (تناسب معنایی {semantic_score:.0%})؛ "
            f"{location_note}؛ نرخ موفقیت {success_score:.0%}."
        )
