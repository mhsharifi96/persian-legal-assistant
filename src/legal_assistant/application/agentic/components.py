from __future__ import annotations

import json
from typing import Any, Protocol, Sequence, cast

from legal_assistant.application.ports import LLMPort
from legal_assistant.application.agentic.state import (
    Intent,
    JudgeVerdict,
    NextAction,
    RouterDecision,
)
from legal_assistant.domain.models import Citation, RetrievedContext

# Stable task tags placed on the first line of each system message. They let a
# fake LLM answer deterministically per node regardless of call order, and make
# routing of structured prompts explicit.
TASK_ROUTER = "router"
TASK_DECOMPOSE = "decompose"
TASK_JUDGE = "judge"
TASK_GENERATE = "generate"

_VALID_INTENTS: frozenset[str] = frozenset(
    {
        "legal_advice",
        "document_analysis",
        "general_chat",
        "out_of_scope",
        "lawyer_recommendation",
    }
)
_VALID_NEXT_ACTIONS: frozenset[str] = frozenset(
    {"retrieve_more", "decompose_again", "finalize"}
)


# --- Node component contracts -------------------------------------------------
# The graph depends on these Protocols, not concrete classes, so tests can
# inject stubs and a future provider can supply richer implementations.


class RouterPort(Protocol):
    def route(
        self, query: str, chat_history: Sequence[dict[str, Any]]
    ) -> RouterDecision: ...


class DecomposerPort(Protocol):
    def decompose(
        self, query: str, *, feedback: Sequence[str] = ()
    ) -> list[str]: ...


class JudgePort(Protocol):
    def judge(
        self, query: str, context: Sequence[RetrievedContext]
    ) -> JudgeVerdict: ...


class GeneratorPort(Protocol):
    def generate(
        self,
        query: str,
        context: Sequence[RetrievedContext],
        *,
        limited: bool,
        feedback: Sequence[str] = (),
        supplementary_analysis: str = "",
    ) -> tuple[str, list[Citation]]: ...


def _load_json(response: str | dict[str, Any]) -> dict[str, Any]:
    data = json.loads(response) if isinstance(response, str) else response
    if not isinstance(data, dict):
        raise ValueError("LLM response must be a JSON object")
    return data


def _system(task: str, instructions: str) -> dict[str, Any]:
    return {"role": "system", "content": f"TASK={task}\n{instructions}"}


# --- LLM-backed implementations ----------------------------------------------


class LLMIntentRouter:
    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    def route(
        self, query: str, chat_history: Sequence[dict[str, Any]]
    ) -> RouterDecision:
        response = self._llm.complete(
            [
                _system(
                    TASK_ROUTER,
                    "Classify the user's Persian message into one intent: "
                    "legal_advice, document_analysis, general_chat, out_of_scope, "
                    "or lawyer_recommendation. Reply as JSON with keys intent, "
                    "confidence, reason.",
                ),
                {"role": "user", "content": query},
            ],
            response_schema={"type": "object"},
        )
        data = _load_json(response)
        intent = str(data.get("intent", "legal_advice"))
        if intent not in _VALID_INTENTS:
            intent = "out_of_scope"
        return RouterDecision(
            intent=cast(Intent, intent),
            confidence=float(data.get("confidence", 0.0)),
            reason=str(data.get("reason", "")),
        )


class LLMQueryDecomposer:
    def __init__(self, llm: LLMPort, *, max_queries: int = 6) -> None:
        self._llm = llm
        self._max_queries = max_queries

    def decompose(self, query: str, *, feedback: Sequence[str] = ()) -> list[str]:
        instructions = (
            "Split the complex Persian legal question into 2-6 atomic retrieval "
            "queries. Reply as JSON with key queries (a list of strings)."
        )
        if feedback:
            instructions += " Prior retrieval was insufficient because: " + "؛ ".join(
                feedback
            )
        response = self._llm.complete(
            [
                _system(TASK_DECOMPOSE, instructions),
                {"role": "user", "content": query},
            ],
            response_schema={"type": "object"},
        )
        data = _load_json(response)
        raw = data.get("queries", [])
        queries = [str(item).strip() for item in raw if str(item).strip()]
        if not queries:
            queries = [query]
        return queries[: self._max_queries]


class LLMLegalJudge:
    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    def judge(
        self, query: str, context: Sequence[RetrievedContext]
    ) -> JudgeVerdict:
        if not context:
            return JudgeVerdict(
                is_valid=False,
                feedback=("هیچ منبع قانونی مرتبطی بازیابی نشد.",),
                next_action="retrieve_more",
            )
        payload = {
            "question": query,
            "context": [
                {"chunk_id": item.chunk_id, "text": item.text} for item in context
            ],
        }
        response = self._llm.complete(
            [
                _system(
                    TASK_JUDGE,
                    "Judge whether the retrieved Persian legal context is "
                    "sufficient, on-topic, temporally valid, and in the correct "
                    "jurisdiction to answer the question. Reply as JSON with keys "
                    "is_valid (bool), feedback (list of strings), next_action "
                    "(retrieve_more | decompose_again | finalize).",
                ),
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_schema={"type": "object"},
        )
        data = _load_json(response)
        is_valid = bool(data.get("is_valid", False))
        feedback = tuple(
            str(item) for item in data.get("feedback", []) if str(item).strip()
        )
        next_action = str(data.get("next_action", "finalize"))
        if next_action not in _VALID_NEXT_ACTIONS:
            next_action = "finalize" if is_valid else "retrieve_more"
        return JudgeVerdict(
            is_valid=is_valid,
            feedback=feedback,
            next_action=cast(NextAction, next_action),
        )


# Persian answer template sections (see agentic-core-contracts.md).
_SUMMARY_HEADER = "خلاصه پاسخ:"
_BASIS_HEADER = "مبنای قانونی:"
_ANALYSIS_HEADER = "تحلیل:"
_CAUTION_HEADER = "محدودیت و هشدار:"
_INSUFFICIENT_CAUTION = (
    "بر اساس منابع بازیابی‌شده اطلاعات کافی برای پاسخ قطعی وجود ندارد؛ این پاسخ "
    "محدود است و نباید جایگزین مشاوره حقوقی تخصصی تلقی شود."
)


def _render_citation(context: RetrievedContext) -> str:
    if context.citations:
        return context.citations[0]
    return context.chunk_id


class PersianAnswerGenerator:
    """Produces the formal Persian answer and grounds every citation by
    ``chunk_id`` against the retrieved context."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    def generate(
        self,
        query: str,
        context: Sequence[RetrievedContext],
        *,
        limited: bool,
        feedback: Sequence[str] = (),
        supplementary_analysis: str = "",
    ) -> tuple[str, list[Citation]]:
        by_id = {item.chunk_id: item for item in context}
        summary = ""
        analysis = ""
        cited_ids: list[str] = []

        if context:
            payload = {
                "question": query,
                "context": [
                    {
                        "chunk_id": item.chunk_id,
                        "text": item.text,
                        "citation": _render_citation(item),
                    }
                    for item in context
                ],
            }
            response = self._llm.complete(
                [
                    _system(
                        TASK_GENERATE,
                        "Answer the Persian legal question in formal Persian using "
                        "ONLY the provided context. Reply as JSON with keys summary, "
                        "analysis, and cited_chunk_ids (a list of chunk_id values you "
                        "actually relied on). Do not invent chunk ids.",
                    ),
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                response_schema={"type": "object"},
            )
            data = _load_json(response)
            summary = str(data.get("summary", "")).strip()
            analysis = str(data.get("analysis", "")).strip()
            cited_ids = [
                str(cid) for cid in data.get("cited_chunk_ids", []) if str(cid) in by_id
            ]

        # Grounding: only cite chunk_ids that are actually present in context.
        # If the model cited nothing valid, fall back to citing all context so
        # the answer is never uncited while claiming legal basis.
        if not cited_ids and context:
            cited_ids = [item.chunk_id for item in context]
        citations = [
            Citation(chunk_id=cid, text=_render_citation(by_id[cid]))
            for cid in dict.fromkeys(cited_ids)
        ]

        answer = self._render(
            summary=summary,
            analysis=analysis,
            citations=citations,
            limited=limited,
            feedback=feedback,
            supplementary_analysis=supplementary_analysis,
        )
        return answer, citations

    def _render(
        self,
        *,
        summary: str,
        analysis: str,
        citations: Sequence[Citation],
        limited: bool,
        feedback: Sequence[str],
        supplementary_analysis: str,
    ) -> str:
        lines: list[str] = [_SUMMARY_HEADER]
        lines.append(summary or "پاسخ قطعی بر اساس منابع در دسترس قابل ارائه نیست.")
        lines.append("")
        lines.append(_BASIS_HEADER)
        if citations:
            lines.extend(f"- [{citation.text}]" for citation in citations)
        else:
            lines.append("- منبع قانونی مستندی در دسترس نیست.")
        lines.append("")
        lines.append(_ANALYSIS_HEADER)
        lines.append(analysis or "تحلیل مبتنی بر منابع بازیابی‌شده ارائه نشده است.")
        if supplementary_analysis:
            lines.append(supplementary_analysis)
        lines.append("")
        lines.append(_CAUTION_HEADER)
        if limited:
            lines.append(_INSUFFICIENT_CAUTION)
            lines.extend(f"- {note}" for note in feedback)
        else:
            lines.append(
                "این پاسخ صرفاً بر پایه منابع بازیابی‌شده است و جایگزین مشاوره "
                "حقوقی تخصصی نیست."
            )
        return "\n".join(lines).strip()
