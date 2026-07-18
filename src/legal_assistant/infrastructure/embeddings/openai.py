from __future__ import annotations

from typing import Sequence

from langchain_openai import OpenAIEmbeddings


class OpenAIEmbeddingModel:
    """LangChain OpenAI embeddings adapter for ``EmbeddingModelPort``."""

    def __init__(
        self,
        *,
        model_name: str,
        dimensions: int,
        api_key: str = "",
        base_url: str = "",
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        embeddings: OpenAIEmbeddings | None = None,
    ) -> None:
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        self._dimension = dimensions
        self._embeddings = embeddings or OpenAIEmbeddings(
            model=model_name,
            dimensions=dimensions,
            api_key=api_key or None,
            base_url=base_url or None,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embeddings.embed_documents(list(texts))

    def embed_query(self, text: str) -> list[float]:
        return self._embeddings.embed_query(text)
