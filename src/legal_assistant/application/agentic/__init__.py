"""Phase 2 agentic reasoning core.

A dependency-free, typed state machine that turns a Persian legal question into
a verified, citation-grounded answer. The core depends only on application
ports (``LLMPort``, ``HybridRetrieverPort``, optional ``CrewAnalysisPort`` and
``CheckpointRepository``) so no vendor SDK (LangGraph, CrewAI, OpenAI, ...)
leaks into the reasoning logic. A future LangGraph adapter can wrap the same
node functions without changing them.
"""

from legal_assistant.application.agentic.graph import LegalQAGraph
from legal_assistant.application.agentic.state import (
    AgentState,
    Intent,
    JudgeVerdict,
    NextAction,
    RouterDecision,
)

__all__ = [
    "AgentState",
    "Intent",
    "JudgeVerdict",
    "LegalQAGraph",
    "NextAction",
    "RouterDecision",
]
