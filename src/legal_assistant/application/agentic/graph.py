from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any, Sequence

from legal_assistant.application.agentic.components import (
    DecomposerPort,
    GeneratorPort,
    JudgePort,
    RouterPort,
)
from legal_assistant.application.agentic.state import AgentState, Intent
from legal_assistant.application.ports import (
    CheckpointRepository,
    CrewAnalysisPort,
    HybridRetrieverPort,
)
from legal_assistant.domain.models import RetrievedContext

# Terminal, non-retrieval responses for router-classified branches.
_GENERAL_CHAT_REPLY = (
    "سلام! من دستیار حقوقی هستم و می‌توانم درباره پرسش‌های حقوقی ایران کمک کنم. "
    "لطفاً سؤال حقوقی خود را مطرح کنید."
)
_OUT_OF_SCOPE_REPLY = (
    "این پرسش خارج از حوزه حقوق ایران است و من نمی‌توانم درباره آن پاسخ حقوقی "
    "ارائه کنم. لطفاً پرسشی مرتبط با حقوق ایران مطرح کنید."
)
_LAWYER_HANDOFF_REPLY = (
    "برای این درخواست، توصیه وکیل مناسب لازم است. پرسش شما به بخش پیشنهاد وکیل "
    "ارجاع داده می‌شود."
)

_RETRIEVAL_INTENTS: frozenset[Intent] = frozenset(
    {"legal_advice", "document_analysis"}
)


def _count_tokens(text: str) -> int:
    return len(text.split())


class LegalQAGraph:
    """Bounded self-reflection reasoning graph.

    Flow: router -> decompose -> retrieve -> judge; valid -> generate;
    invalid and retries remain -> re-retrieve/re-decompose; invalid and
    retries exhausted -> limited answer with an explicit insufficiency warning.
    """

    def __init__(
        self,
        *,
        router: RouterPort,
        decomposer: DecomposerPort,
        judge: JudgePort,
        generator: GeneratorPort,
        retriever: HybridRetrieverPort,
        crew: CrewAnalysisPort | None = None,
        checkpoint: CheckpointRepository | None = None,
        max_retries: int = 2,
        retrieval_top_k: int = 8,
        max_context_tokens: int = 2000,
        retrieval_max_workers: int = 4,
    ) -> None:
        self._router = router
        self._decomposer = decomposer
        self._judge = judge
        self._generator = generator
        self._retriever = retriever
        self._crew = crew
        self._checkpoint = checkpoint
        self._max_retries = max_retries
        self._retrieval_top_k = retrieval_top_k
        self._max_context_tokens = max_context_tokens
        self._retrieval_max_workers = max(1, retrieval_max_workers)

    # --- Entry point ---------------------------------------------------------

    def run(
        self,
        user_query: str,
        chat_history: Sequence[dict[str, Any]] | None = None,
        *,
        thread_id: str | None = None,
    ) -> AgentState:
        state = AgentState(
            user_query=user_query,
            chat_history=list(chat_history or []),
        )

        self.router_node(state)
        if state.intent not in _RETRIEVAL_INTENTS:
            self._checkpoint_state(thread_id, state)
            return state

        self.decompose_node(state)
        self.retrieval_node(state)
        self.judge_node(state)

        while not state.is_valid and state.retry_count < self._max_retries:
            state.retry_count += 1
            if state.next_action == "decompose_again" and state.verification_feedback:
                self.decompose_node(state, feedback=state.verification_feedback)
            self.retrieval_node(state)
            self.judge_node(state)

        state.limited = not state.is_valid
        self.generation_node(state)
        self._checkpoint_state(thread_id, state)
        return state

    # --- Nodes (individually testable) --------------------------------------

    def router_node(self, state: AgentState) -> AgentState:
        decision = self._router.route(state.user_query, state.chat_history)
        state.intent = decision.intent
        if decision.intent == "general_chat":
            state.draft_response = _GENERAL_CHAT_REPLY
        elif decision.intent == "out_of_scope":
            state.draft_response = _OUT_OF_SCOPE_REPLY
        elif decision.intent == "lawyer_recommendation":
            state.draft_response = _LAWYER_HANDOFF_REPLY
            state.handoff = "lawyer_recommendation"
        return state

    def decompose_node(
        self, state: AgentState, *, feedback: Sequence[str] = ()
    ) -> AgentState:
        state.decomposed_queries = self._decomposer.decompose(
            state.user_query, feedback=feedback
        )
        return state

    def retrieval_node(self, state: AgentState) -> AgentState:
        queries = state.decomposed_queries or [state.user_query]
        # Concurrency is confined to this single boundary (the skill's
        # sync-via-thread-pool option) rather than scattered through nodes.
        if len(queries) == 1:
            per_query = [self._retrieve_one(queries[0])]
        else:
            with ThreadPoolExecutor(
                max_workers=min(self._retrieval_max_workers, len(queries))
            ) as executor:
                per_query = list(executor.map(self._retrieve_one, queries))
        state.retrieved_context = self._assemble_context(per_query)
        return state

    def judge_node(self, state: AgentState) -> AgentState:
        verdict = self._judge.judge(state.user_query, state.retrieved_context)
        state.is_valid = verdict.is_valid
        state.verification_feedback = list(verdict.feedback)
        state.next_action = verdict.next_action
        return state

    def generation_node(self, state: AgentState) -> AgentState:
        supplementary = ""
        if self._crew is not None and state.retrieved_context and not state.limited:
            supplementary = self._crew.analyze(
                state.user_query, state.retrieved_context
            )
        answer, citations = self._generator.generate(
            state.user_query,
            state.retrieved_context,
            limited=state.limited,
            feedback=state.verification_feedback,
            supplementary_analysis=supplementary,
        )
        state.draft_response = answer
        state.citations = citations
        return state

    # --- Helpers -------------------------------------------------------------

    def _retrieve_one(self, query: str) -> list[RetrievedContext]:
        return self._retriever.retrieve(query, top_k=self._retrieval_top_k)

    def _assemble_context(
        self, per_query: Sequence[list[RetrievedContext]]
    ) -> list[RetrievedContext]:
        """Merge subquery results: deduplicate by chunk_id keeping the highest
        score, then enforce a token budget over the combined context."""
        best: dict[str, RetrievedContext] = {}
        for results in per_query:
            for context in results:
                existing = best.get(context.chunk_id)
                if existing is None or context.score > existing.score:
                    best[context.chunk_id] = context

        ordered = sorted(best.values(), key=lambda item: item.score, reverse=True)
        budgeted: list[RetrievedContext] = []
        used_tokens = 0
        for context in ordered:
            tokens = _count_tokens(context.text)
            if budgeted and used_tokens + tokens > self._max_context_tokens:
                continue
            budgeted.append(context)
            used_tokens += tokens
        return budgeted

    def _checkpoint_state(self, thread_id: str | None, state: AgentState) -> None:
        if self._checkpoint is None or thread_id is None:
            return
        snapshot = {
            "user_query": state.user_query,
            "intent": state.intent,
            "draft_response": state.draft_response,
            "citations": [asdict(citation) for citation in state.citations],
            "retry_count": state.retry_count,
            "is_valid": state.is_valid,
            "limited": state.limited,
        }
        self._checkpoint.save(thread_id, snapshot)
