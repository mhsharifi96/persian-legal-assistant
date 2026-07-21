from __future__ import annotations

from collections.abc import Sequence

from langchain_openai import ChatOpenAI

from legal_assistant.application.research import LegalResearchService
from legal_assistant.domain.research import LegalEvidence
from legal_assistant.infrastructure.agents.deepagents_runtime import (
    DeepAgentRuntime,
    _InvocationLedger,
)


class EmptyVectorSearch:
    def search(self, query: str, *, top_k: int) -> list[LegalEvidence]:
        return []


class EmptyGraphSearch:
    def expand(
        self,
        entity_ids: Sequence[str],
        *,
        depth: int,
        limit: int,
    ) -> list[LegalEvidence]:
        return []


def test_current_deepagents_api_builds_constrained_agent_without_network() -> None:
    runtime = DeepAgentRuntime(
        LegalResearchService(EmptyVectorSearch(), EmptyGraphSearch()),
        model=ChatOpenAI(model="gpt-5-mini", api_key="test-key"),
        profile_key="openai:gpt-5-mini",
    )

    tools = runtime._build_tools(_InvocationLedger(max_tool_calls=4))
    agent = runtime._build_agent(tools)

    assert agent is not None
    assert len(runtime._skill_documents) == 4
    assert "SubAgentMiddleware.before_agent" not in agent.nodes
