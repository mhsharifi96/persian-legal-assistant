from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Any

from openai import OpenAI


class HashingEmbeddingProvider:
    """Deterministic local lexical embeddings for development and tests."""

    def __init__(self, dimension: int = 384) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be greater than zero")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for token in re.findall(r"\w+", text.casefold(), flags=re.UNICODE):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:8], "big") % self._dimension
            vector[index] += 1.0 if digest[8] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        *,
        model_name: str,
        dimension: int,
        api_key: str,
        base_url: str | None = None,
        batch_size: int = 64,
        client: Any | None = None,
    ) -> None:
        if not api_key and client is None:
            raise ValueError("OPENAI_API_KEY is required")
        self._model_name = model_name
        self._dimension = dimension
        self._batch_size = batch_size
        self._client = client or OpenAI(api_key=api_key, base_url=base_url or None)

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        output: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            response = self._client.embeddings.create(
                model=self._model_name,
                input=list(texts[start : start + self._batch_size]),
                dimensions=self._dimension,
            )
            output.extend(item.embedding for item in sorted(response.data, key=lambda x: x.index))
        return output
