from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Mapping


class AuthorityTier(StrEnum):
    """How strongly a retrieved source may support a legal conclusion."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    AUXILIARY = "auxiliary"


ChatRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: ChatRole
    content: str


@dataclass(frozen=True)
class LegalEvidence:
    """One retrievable, attributable piece of legal research evidence."""

    evidence_id: str
    entity_id: str
    title: str
    text: str
    source_type: str
    authority: AuthorityTier
    score: float
    source_uri: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class LegalCitation:
    """A citation grounded to evidence actually returned by a search tool."""

    source_id: str
    evidence_id: str
    entity_id: str
    title: str
    authority: AuthorityTier
    source_uri: str = ""
    excerpt: str = ""


@dataclass(frozen=True)
class AgentAnswer:
    answer: str
    citations: tuple[LegalCitation, ...] = ()
    limitations: tuple[str, ...] = ()
    limited: bool = False
    tool_calls: int = 0
