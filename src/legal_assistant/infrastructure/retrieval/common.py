from __future__ import annotations

from collections.abc import Iterable

from legal_assistant.domain.research import AuthorityTier

_PRIMARY_LABELS = frozenset(
    {
        "Article",
        "Note",
        "Law",
        "LegalDecision",
        "LegalProvision",
        "UnanimityDecision",
    }
)
_AUXILIARY_LABELS = frozenset({"Question", "Answer", "Lawyer", "Tag"})
_TYPE_PRIORITY = (
    "Article",
    "Note",
    "UnanimityDecision",
    "LegalDecision",
    "LegalProvision",
    "Law",
    "Question",
    "Answer",
    "Lawyer",
    "Tag",
)


def string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, Iterable):
        return []
    return [str(item) for item in value if item is not None]


def classify_authority(
    labels: Iterable[str], *, access_status: str = ""
) -> AuthorityTier:
    normalized = frozenset(labels)
    if normalized & _AUXILIARY_LABELS or "DadrahNode" in normalized:
        return AuthorityTier.AUXILIARY
    if access_status == "reference_only":
        return AuthorityTier.SECONDARY
    if normalized & _PRIMARY_LABELS:
        return AuthorityTier.PRIMARY
    return AuthorityTier.SECONDARY


def preferred_source_type(labels: Iterable[str], fallback: str = "legal_source") -> str:
    normalized = frozenset(labels)
    return next((label for label in _TYPE_PRIORITY if label in normalized), fallback)
