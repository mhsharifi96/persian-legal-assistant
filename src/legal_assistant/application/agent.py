from __future__ import annotations

from collections.abc import Sequence

from legal_assistant.application.ports import LegalAgentRuntimePort
from legal_assistant.domain.research import AgentAnswer, ChatMessage


class LegalAgentService:
    """Application entry point for one grounded legal-assistant turn."""

    def __init__(
        self,
        runtime: LegalAgentRuntimePort,
        *,
        max_question_chars: int = 12_000,
        max_history_messages: int = 20,
    ) -> None:
        if max_question_chars <= 0:
            raise ValueError("max_question_chars must be greater than zero")
        if max_history_messages < 0:
            raise ValueError("max_history_messages must not be negative")
        self._runtime = runtime
        self._max_question_chars = max_question_chars
        self._max_history_messages = max_history_messages

    def ask(
        self,
        question: str,
        *,
        history: Sequence[ChatMessage] = (),
        thread_id: str | None = None,
    ) -> AgentAnswer:
        normalized = question.strip()
        if not normalized:
            raise ValueError("question must not be empty")
        if len(normalized) > self._max_question_chars:
            raise ValueError(
                f"question exceeds the {self._max_question_chars} character limit"
            )
        safe_history = (
            tuple(history[-self._max_history_messages :])
            if self._max_history_messages
            else ()
        )
        return self._runtime.answer(
            normalized,
            history=safe_history,
            thread_id=thread_id,
        )
