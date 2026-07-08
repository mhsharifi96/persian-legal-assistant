from __future__ import annotations

from typing import Any, Sequence

from legal_assistant.application.agentic.components import (
    LLMIntentRouter,
    LLMLegalJudge,
    LLMQueryDecomposer,
    PersianAnswerGenerator,
)
from legal_assistant.application.agentic.graph import LegalQAGraph
from legal_assistant.config.bootstrap import build_agentic_graph
from legal_assistant.config.settings import Settings
from legal_assistant.domain.models import LegalHierarchy, RetrievedContext
from legal_assistant.infrastructure.fakes import (
    FakeCrewAnalysis,
    InMemoryCheckpointRepository,
    TaggedFakeLLM,
)


class StubRetriever:
    """Fake ``HybridRetrieverPort`` returning preset contexts per query."""

    def __init__(
        self,
        by_query: dict[str, list[RetrievedContext]] | None = None,
        default: list[RetrievedContext] | None = None,
    ) -> None:
        self._by_query = by_query or {}
        self._default = default or []
        self.queries: list[str] = []

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedContext]:
        self.queries.append(query)
        return list(self._by_query.get(query, self._default))


def _context(chunk_id: str, text: str, score: float = 0.9) -> RetrievedContext:
    return RetrievedContext(
        chunk_id=chunk_id,
        text=text,
        score=score,
        source="vector",
        hierarchy=LegalHierarchy(article_number="10"),
        citations=("قانون مدنی، ماده ۱۰",),
    )


def _build_graph(
    llm: TaggedFakeLLM,
    retriever: StubRetriever,
    **kwargs: Any,
) -> LegalQAGraph:
    return LegalQAGraph(
        router=LLMIntentRouter(llm),
        decomposer=LLMQueryDecomposer(llm),
        judge=LLMLegalJudge(llm),
        generator=PersianAnswerGenerator(llm),
        retriever=retriever,
        **kwargs,
    )


def test_happy_path_generates_grounded_persian_answer() -> None:
    retriever = StubRetriever(default=[_context("civil:10:p0", "ماده ۱۰ قانون مدنی...")])
    llm = TaggedFakeLLM()  # all defaults: legal_advice, valid judge
    graph = _build_graph(llm, retriever)

    state = graph.run("آیا قرارداد خصوصی معتبر است؟")

    assert state.intent == "legal_advice"
    assert state.is_valid is True
    assert state.limited is False
    assert state.retry_count == 0
    assert [c.chunk_id for c in state.citations] == ["civil:10:p0"]
    assert "خلاصه پاسخ:" in state.draft_response
    assert "مبنای قانونی:" in state.draft_response
    assert "قانون مدنی، ماده ۱۰" in state.draft_response


def test_insufficient_context_triggers_reretrieval_then_succeeds() -> None:
    retriever = StubRetriever(default=[_context("civil:10:p0", "ماده ۱۰ قانون مدنی...")])
    llm = TaggedFakeLLM(
        scripts={
            "judge": [
                {"is_valid": False, "feedback": ["ناکافی"], "next_action": "retrieve_more"},
                {"is_valid": True, "feedback": [], "next_action": "finalize"},
            ]
        }
    )
    graph = _build_graph(llm, retriever, max_retries=2)

    state = graph.run("سوال حقوقی پیچیده")

    assert state.retry_count == 1
    assert state.is_valid is True
    assert state.limited is False


def test_max_retry_fallback_produces_limited_answer_with_warning() -> None:
    retriever = StubRetriever(default=[_context("civil:10:p0", "ماده ۱۰ قانون مدنی...")])
    llm = TaggedFakeLLM(
        scripts={
            "judge": [
                {"is_valid": False, "feedback": ["ناکافی ۱"], "next_action": "retrieve_more"},
                {"is_valid": False, "feedback": ["ناکافی ۲"], "next_action": "retrieve_more"},
                {"is_valid": False, "feedback": ["ناکافی ۳"], "next_action": "retrieve_more"},
            ]
        }
    )
    graph = _build_graph(llm, retriever, max_retries=2)

    state = graph.run("سوال بدون منبع کافی")

    assert state.retry_count == 2
    assert state.is_valid is False
    assert state.limited is True
    assert "محدودیت و هشدار:" in state.draft_response
    assert "این پاسخ" in state.draft_response


def test_general_chat_route_skips_retrieval() -> None:
    retriever = StubRetriever(default=[_context("civil:10:p0", "متن")])
    llm = TaggedFakeLLM(scripts={"router": [{"intent": "general_chat", "confidence": 1.0}]})
    graph = _build_graph(llm, retriever)

    state = graph.run("سلام")

    assert state.intent == "general_chat"
    assert state.retrieved_context == []
    assert retriever.queries == []
    assert "دستیار حقوقی" in state.draft_response


def test_out_of_scope_route_refuses() -> None:
    retriever = StubRetriever()
    llm = TaggedFakeLLM(scripts={"router": [{"intent": "out_of_scope", "confidence": 0.9}]})
    graph = _build_graph(llm, retriever)

    state = graph.run("دستور پخت غذا چیست؟")

    assert state.intent == "out_of_scope"
    assert retriever.queries == []
    assert "خارج از حوزه" in state.draft_response


def test_lawyer_recommendation_hands_off() -> None:
    retriever = StubRetriever()
    llm = TaggedFakeLLM(
        scripts={"router": [{"intent": "lawyer_recommendation", "confidence": 0.8}]}
    )
    graph = _build_graph(llm, retriever)

    state = graph.run("یک وکیل خوب معرفی کن")

    assert state.intent == "lawyer_recommendation"
    assert state.handoff == "lawyer_recommendation"
    assert retriever.queries == []


def test_generation_grounds_citations_by_chunk_id() -> None:
    retriever = StubRetriever(default=[_context("civil:10:p0", "ماده ۱۰ قانون مدنی...")])
    llm = TaggedFakeLLM(
        scripts={
            "generate": [
                {
                    "summary": "خلاصه",
                    "analysis": "تحلیل",
                    # includes a hallucinated id that must be dropped
                    "cited_chunk_ids": ["civil:10:p0", "does-not-exist:99"],
                }
            ]
        }
    )
    graph = _build_graph(llm, retriever)

    state = graph.run("سوال حقوقی")

    assert [c.chunk_id for c in state.citations] == ["civil:10:p0"]


def test_context_assembly_deduplicates_across_subqueries() -> None:
    shared = _context("civil:10:p0", "ماده ۱۰", score=0.5)
    shared_hi = _context("civil:10:p0", "ماده ۱۰", score=0.9)
    other = _context("civil:11:p0", "ماده ۱۱", score=0.7)
    retriever = StubRetriever(
        by_query={"q1": [shared], "q2": [shared_hi, other]}
    )
    llm = TaggedFakeLLM(scripts={"decompose": [{"queries": ["q1", "q2"]}]})
    graph = _build_graph(llm, retriever)

    state = graph.run("سوال چندبخشی")

    ids = [c.chunk_id for c in state.retrieved_context]
    assert ids == ["civil:10:p0", "civil:11:p0"]  # deduped, highest score first
    top = next(c for c in state.retrieved_context if c.chunk_id == "civil:10:p0")
    assert top.score == 0.9


def test_crew_analysis_folds_into_valid_answer() -> None:
    retriever = StubRetriever(default=[_context("civil:10:p0", "ماده ۱۰")])
    llm = TaggedFakeLLM()
    crew = FakeCrewAnalysis(analysis="تحلیل کارشناسی تکمیلی")
    graph = _build_graph(llm, retriever, crew=crew)

    state = graph.run("سوال حقوقی")

    assert crew.calls == ["سوال حقوقی"]
    assert "تحلیل کارشناسی تکمیلی" in state.draft_response


def test_checkpoint_saves_final_state() -> None:
    retriever = StubRetriever(default=[_context("civil:10:p0", "ماده ۱۰")])
    llm = TaggedFakeLLM()
    checkpoint = InMemoryCheckpointRepository()
    graph = _build_graph(llm, retriever, checkpoint=checkpoint)

    graph.run("سوال حقوقی", thread_id="t-1")

    saved = checkpoint.load("t-1")
    assert saved is not None
    assert saved["intent"] == "legal_advice"
    assert saved["citations"][0]["chunk_id"] == "civil:10:p0"


def test_bootstrap_build_agentic_graph_runs_end_to_end() -> None:
    settings = Settings()  # fake providers by default
    graph = build_agentic_graph(settings)

    state = graph.run("پرسش حقوقی نمونه")

    assert state.intent == "legal_advice"
    assert isinstance(state.draft_response, str)
    assert "خلاصه پاسخ:" in state.draft_response
