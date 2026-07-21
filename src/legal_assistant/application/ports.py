from __future__ import annotations

from typing import Protocol, Sequence

from legal_assistant.domain.research import AgentAnswer, ChatMessage, LegalEvidence


class EmbeddingModelPort(Protocol):
    @property
    def dimension(self) -> int: ...

    def embed_query(self, text: str) -> list[float]: ...


class LegalVectorSearchPort(Protocol):
    def search(self, query: str, *, top_k: int) -> list[LegalEvidence]: ...


class LegalGraphSearchPort(Protocol):
    def expand(
        self,
        entity_ids: Sequence[str],
        *,
        depth: int,
        limit: int,
    ) -> list[LegalEvidence]: ...


class LegalAgentRuntimePort(Protocol):
    def answer(
        self,
        question: str,
        *,
        history: Sequence[ChatMessage] = (),
        thread_id: str | None = None,
    ) -> AgentAnswer: ...
