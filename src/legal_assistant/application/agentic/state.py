from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from legal_assistant.domain.models import Citation, RetrievedContext

Intent = Literal[
    "legal_advice",
    "document_analysis",
    "general_chat",
    "out_of_scope",
    "lawyer_recommendation",
]

# What the judge asks the graph to do next when context is insufficient.
NextAction = Literal["retrieve_more", "decompose_again", "finalize"]


@dataclass(frozen=True)
class RouterDecision:
    intent: Intent
    confidence: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class JudgeVerdict:
    is_valid: bool
    feedback: tuple[str, ...] = ()
    next_action: NextAction = "finalize"


@dataclass
class AgentState:
    """Typed, serializable-by-construction state passed between nodes.

    Kept as a plain mutable dataclass (not a vendor state type) so nodes are
    individually testable and a checkpoint adapter can snapshot it.
    """

    user_query: str
    intent: Intent | None = None
    decomposed_queries: list[str] = field(default_factory=list)
    retrieved_context: list[RetrievedContext] = field(default_factory=list)
    draft_response: str = ""
    verification_feedback: list[str] = field(default_factory=list)
    is_valid: bool = False
    next_action: NextAction = "finalize"
    chat_history: list[dict[str, Any]] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    retry_count: int = 0
    # True when the answer was produced without sufficient/valid context after
    # exhausting retries; generation must then emit an explicit warning.
    limited: bool = False
    # Set when the router hands the query off to another subsystem (e.g. the
    # Phase 3 lawyer recommender) instead of answering directly.
    handoff: str | None = None
