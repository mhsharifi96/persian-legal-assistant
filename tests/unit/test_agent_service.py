from __future__ import annotations

from collections.abc import Sequence

import pytest

from legal_assistant.application.agent import LegalAgentService
from legal_assistant.domain.research import AgentAnswer, ChatMessage


class StubRuntime:
    def __init__(self) -> None:
        self.question = ""
        self.history: tuple[ChatMessage, ...] = ()
        self.thread_id: str | None = None

    def answer(
        self,
        question: str,
        *,
        history: Sequence[ChatMessage] = (),
        thread_id: str | None = None,
    ) -> AgentAnswer:
        self.question = question
        self.history = tuple(history)
        self.thread_id = thread_id
        return AgentAnswer(answer="پاسخ")


def test_agent_service_normalizes_and_caps_history() -> None:
    runtime = StubRuntime()
    service = LegalAgentService(runtime, max_history_messages=2)
    history = [
        ChatMessage(role="user", content="یک"),
        ChatMessage(role="assistant", content="دو"),
        ChatMessage(role="user", content="سه"),
    ]

    answer = service.ask("  پرسش حقوقی  ", history=history, thread_id="thread-1")

    assert answer.answer == "پاسخ"
    assert runtime.question == "پرسش حقوقی"
    assert [item.content for item in runtime.history] == ["دو", "سه"]
    assert runtime.thread_id == "thread-1"


def test_agent_service_rejects_empty_and_oversized_questions() -> None:
    service = LegalAgentService(StubRuntime(), max_question_chars=4)

    with pytest.raises(ValueError, match="must not be empty"):
        service.ask("   ")
    with pytest.raises(ValueError, match="exceeds"):
        service.ask("12345")


def test_agent_service_can_disable_history() -> None:
    runtime = StubRuntime()
    service = LegalAgentService(runtime, max_history_messages=0)

    service.ask("پرسش", history=[ChatMessage(role="user", content="قدیمی")])

    assert runtime.history == ()
