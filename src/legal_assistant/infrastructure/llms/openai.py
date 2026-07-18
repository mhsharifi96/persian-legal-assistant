from __future__ import annotations

import json
from typing import Any

from langchain_openai import ChatOpenAI


class OpenAILLM:
    """LangChain ``ChatOpenAI`` adapter with JSON-mode structured responses.

    LangSmith automatically traces these invocations when
    ``LANGSMITH_TRACING=true`` is configured in the runtime environment.
    """

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str = "",
        base_url: str = "",
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        chat_model: ChatOpenAI | None = None,
    ) -> None:
        self._model_name = model_name
        self._model = chat_model or ChatOpenAI(
            model=model_name,
            api_key=api_key or None,
            base_url=base_url or None,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        response_schema: dict[str, Any] | None = None,
    ) -> str | dict[str, Any]:
        run_name = self._run_name(messages)
        config = {
            "run_name": run_name,
            "metadata": {"provider": "openai", "model": self._model_name},
        }
        if response_schema is not None:
            # Existing application components validate their exact domain
            # schemas. JSON mode guarantees parseable JSON while preserving
            # that vendor-independent validation boundary.
            response = self._model.bind(
                response_format={"type": "json_object"}
            ).invoke(messages, config=config)
            data = json.loads(response.text)
            if not isinstance(data, dict):
                raise ValueError("OpenAI structured response must be a JSON object")
            return data
        return self._model.invoke(messages, config=config).text

    @staticmethod
    def _run_name(messages: list[dict[str, Any]]) -> str:
        for message in messages:
            if message.get("role") != "system":
                continue
            first_line = str(message.get("content", "")).splitlines()[:1]
            if first_line and first_line[0].startswith("TASK="):
                return f"persian-legal-{first_line[0].split('=', 1)[1].strip()}"
        return "persian-legal-completion"
