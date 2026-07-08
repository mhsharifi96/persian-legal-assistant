from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from legal_assistant.domain.models import EvaluationRecord, LawyerProfile


def _iter_json_lines(path: str | Path) -> Iterator[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError("Each JSONL record must be a JSON object")
            yield data


def _normalize_success_rate(value: Any) -> float:
    rate = float(value)
    # Source data may use percentages (0..100); normalize to 0..1 here so the
    # service always sees a normalized rate (contract requirement).
    if rate > 1.0:
        rate = rate / 100.0
    return max(0.0, min(1.0, rate))


def _as_specialties(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    parts = str(value).replace("،", ",").split(",")
    return tuple(part.strip() for part in parts if part.strip())


def lawyer_from_dict(data: dict[str, Any]) -> LawyerProfile:
    return LawyerProfile(
        lawyer_id=str(data["lawyer_id"]),
        full_name=str(data["full_name"]),
        specialties=_as_specialties(data.get("specialties", ())),
        location=str(data.get("location", "")),
        success_rate=_normalize_success_rate(data.get("success_rate", 0.0)),
        metadata=dict(data.get("metadata") or {}),
    )


def evaluation_record_from_dict(data: dict[str, Any]) -> EvaluationRecord:
    return EvaluationRecord(
        question=str(data["question"]),
        answer=str(data.get("answer", "")),
        contexts=tuple(str(c) for c in data.get("contexts", ())),
        ground_truth=str(data.get("ground_truth", "")),
        citations=tuple(str(c) for c in data.get("citations", ())),
        metadata=dict(data.get("metadata") or {}),
    )


class JsonlLawyerRepository:
    """File-backed ``LawyerRepository`` reading a JSONL lawyer dataset."""

    def __init__(self, path: str | Path) -> None:
        self._path = path

    def list_lawyers(
        self, *, filters: dict[str, Any] | None = None
    ) -> list[LawyerProfile]:
        profiles = [lawyer_from_dict(row) for row in _iter_json_lines(self._path)]
        if not filters:
            return profiles
        return [p for p in profiles if _profile_matches(p, filters)]


class JsonlEvaluationRepository:
    """File-backed ``EvaluationRepository`` reading canonical JSONL records."""

    def __init__(self, path: str | Path) -> None:
        self._path = path

    def load_records(self) -> list[EvaluationRecord]:
        return [
            evaluation_record_from_dict(row) for row in _iter_json_lines(self._path)
        ]


def _profile_matches(profile: LawyerProfile, filters: dict[str, Any]) -> bool:
    for key, value in filters.items():
        if key == "specialty":
            if value not in profile.specialties:
                return False
        elif key == "location":
            if profile.location != value:
                return False
        elif profile.metadata.get(key) != value:
            return False
    return True
