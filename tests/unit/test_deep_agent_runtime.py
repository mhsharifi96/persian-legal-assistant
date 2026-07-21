from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Sequence
from typing import Any

from legal_assistant.application.research import LegalResearchService
from legal_assistant.domain.research import AuthorityTier, LegalEvidence
from legal_assistant.infrastructure.agents.deepagents_runtime import (
    DeepAgentRuntime,
    _InvocationLedger,
)


def _primary_evidence() -> LegalEvidence:
    return LegalEvidence(
        evidence_id="qdrant:point-1",
        entity_id="article:10",
        title="ماده ۱۰ قانون مدنی",
        text="قراردادهای خصوصی نسبت به کسانی که آن را منعقد نموده‌اند نافذ است.",
        source_type="Article",
        authority=AuthorityTier.PRIMARY,
        score=0.95,
        source_uri="https://example.test/article/10",
    )


class FakeVector:
    def __init__(self, results: list[LegalEvidence]) -> None:
        self.results = results

    def search(self, query: str, *, top_k: int) -> list[LegalEvidence]:
        return self.results[:top_k]


class FakeGraph:
    def expand(
        self,
        entity_ids: Sequence[str],
        *,
        depth: int,
        limit: int,
    ) -> list[LegalEvidence]:
        return []


class ScriptedAgent:
    def __init__(
        self,
        tools: Sequence[Callable[..., str]],
        *,
        cite: bool,
        call_search: bool = True,
    ) -> None:
        self.tools = tools
        self.cite = cite
        self.call_search = call_search
        self.invocation: dict[str, object] = {}
        self.config: dict[str, object] = {}

    def invoke(
        self, invocation: dict[str, object], *, config: dict[str, object]
    ) -> dict[str, object]:
        self.invocation = invocation
        self.config = config
        source_ids: list[str] = []
        if self.call_search:
            result = json.loads(self.tools[0]("اعتبار قرارداد خصوصی", 6))
            source_ids = [item["source_id"] for item in result.get("results", [])]
        if self.cite and source_ids:
            return {
                "structured_response": {
                    "answer": "اصل آزادی قراردادها در حدود قانون پذیرفته شده است [S1] [S99].",
                    "cited_source_ids": ["S1", "S99"],
                    "limitations": [],
                }
            }
        return {
            "structured_response": {
                "answer": "پاسخ قطعی در دسترس نیست.",
                "cited_source_ids": [],
                "limitations": [],
            }
        }


class ScriptedFactory:
    def __init__(self, *, cite: bool, call_search: bool = True) -> None:
        self.cite = cite
        self.call_search = call_search
        self.kwargs: dict[str, Any] = {}
        self.agent: ScriptedAgent | None = None

    def __call__(self, **kwargs: Any) -> ScriptedAgent:
        self.kwargs = kwargs
        self.agent = ScriptedAgent(
            kwargs["tools"], cite=self.cite, call_search=self.call_search
        )
        return self.agent


def _runtime(
    evidence: list[LegalEvidence], factory: ScriptedFactory
) -> DeepAgentRuntime:
    research = LegalResearchService(FakeVector(evidence), FakeGraph())
    return DeepAgentRuntime(
        research,
        model=object(),
        profile_key="openai:test",
        agent_factory=factory,
        file_data_factory=lambda content: {"content": content},
        skill_documents={
            "/skills/test-skill/SKILL.md": "---\nname: test-skill\ndescription: test\n---\nUse search."
        },
    )


def test_runtime_grounds_citations_and_removes_hallucinated_ids() -> None:
    factory = ScriptedFactory(cite=True)

    answer = _runtime([_primary_evidence()], factory).answer(
        "اعتبار قرارداد خصوصی چیست؟", thread_id="t-1"
    )

    assert answer.limited is False
    assert [citation.source_id for citation in answer.citations] == ["S1"]
    assert "[S99]" not in answer.answer
    assert "[S1]" in answer.answer
    assert "منابع بازیابی‌شده" in answer.answer
    assert answer.tool_calls == 1
    assert factory.kwargs["subagents"] == []
    assert factory.agent is not None
    assert factory.agent.config["recursion_limit"] == 24
    skill_files = factory.agent.invocation["files"]
    assert isinstance(skill_files, dict)
    assert "/skills/test-skill/SKILL.md" in skill_files


def test_runtime_returns_explicit_limited_answer_without_evidence() -> None:
    answer = _runtime([], ScriptedFactory(cite=False)).answer("پرسش بدون منبع")

    assert answer.limited is True
    assert answer.citations == ()
    assert "پاسخ قطعی در دسترس نیست" not in answer.answer
    assert "منابع بازیابی‌شده برای ارائه پاسخ حقوقی مستند کافی نیستند" in answer.answer


def test_graph_tool_rejects_entity_ids_not_returned_by_search() -> None:
    factory = ScriptedFactory(cite=False, call_search=False)
    runtime = _runtime([_primary_evidence()], factory)
    runtime.answer("پرسش")

    assert factory.agent is not None
    result = json.loads(factory.agent.tools[1](["invented:entity"], 1, 5))
    assert result["error"] == "no_known_entity_ids"


def test_ledger_allocates_unique_source_ids_under_concurrency() -> None:
    ledger = _InvocationLedger(max_tool_calls=4)
    evidence = [
        LegalEvidence(
            evidence_id=f"evidence:{index}",
            entity_id=f"entity:{index}",
            title=f"منبع {index}",
            text="متن",
            source_type="Article",
            authority=AuthorityTier.PRIMARY,
            score=0.8,
        )
        for index in range(20)
    ]

    with ThreadPoolExecutor(max_workers=8) as executor:
        payloads = list(executor.map(lambda item: ledger.record([item])[0], evidence))

    assert len({item["source_id"] for item in payloads}) == 20
    assert len(ledger.evidence_by_source) == 20


def test_runtime_marks_answer_with_uncited_paragraph_as_limited() -> None:
    ledger = _InvocationLedger(max_tool_calls=4)
    ledger.record([_primary_evidence()])

    answer = DeepAgentRuntime._ground_answer(
        {
            "answer": (
                "اصل آزادی قراردادها در حدود قانون پذیرفته شده است [S1].\n\n"
                "این بند دوم بدون استناد مستقیم یک نتیجه دیگر بیان می‌کند."
            ),
            "cited_source_ids": ["S1"],
            "limitations": [],
        },
        ledger,
    )

    assert answer.limited is True
    assert "برای همه بخش‌های ماهوی پاسخ" in answer.answer
