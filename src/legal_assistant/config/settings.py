from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


def _env_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AgentSettings:
    """Runtime settings for the legal research agent, independent of Django."""

    model_provider: str = "openai"
    model_name: str = "gpt-5-mini"
    openai_api_key: str = ""
    openai_api_base: str = ""
    openai_timeout_seconds: float = 60.0
    openai_max_retries: int = 2
    openai_use_responses_api: bool = False
    embedding_provider: str = "openai"
    embedding_model_name: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072
    embedding_batch_size: int = 64
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection_name: str = "legal_graph_nodes"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"
    max_search_results: int = 8
    max_graph_depth: int = 2
    max_graph_results: int = 16
    max_tool_calls: int = 4
    recursion_limit: int = 24
    max_evidence_chars: int = 4_000
    max_question_chars: int = 12_000
    max_history_messages: int = 20

    def __post_init__(self) -> None:
        positive_values = {
            "embedding_dimensions": self.embedding_dimensions,
            "embedding_batch_size": self.embedding_batch_size,
            "max_search_results": self.max_search_results,
            "max_graph_depth": self.max_graph_depth,
            "max_graph_results": self.max_graph_results,
            "max_tool_calls": self.max_tool_calls,
            "recursion_limit": self.recursion_limit,
            "max_evidence_chars": self.max_evidence_chars,
            "max_question_chars": self.max_question_chars,
        }
        for name, value in positive_values.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")
        if self.openai_timeout_seconds <= 0:
            raise ValueError("openai_timeout_seconds must be greater than zero")
        if self.openai_max_retries < 0:
            raise ValueError("openai_max_retries must not be negative")
        if self.max_history_messages < 0:
            raise ValueError("max_history_messages must not be negative")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AgentSettings:
        source = env if env is not None else os.environ
        defaults = cls()
        return cls(
            model_provider=source.get("AGENT_MODEL_PROVIDER", defaults.model_provider),
            model_name=source.get("AGENT_MODEL_NAME", defaults.model_name),
            openai_api_key=source.get("OPENAI_API_KEY", defaults.openai_api_key),
            openai_api_base=source.get("OPENAI_API_BASE", defaults.openai_api_base),
            openai_timeout_seconds=float(
                source.get("OPENAI_TIMEOUT_SECONDS", defaults.openai_timeout_seconds)
            ),
            openai_max_retries=int(
                source.get("OPENAI_MAX_RETRIES", defaults.openai_max_retries)
            ),
            openai_use_responses_api=_env_bool(
                source.get("OPENAI_USE_RESPONSES_API"),
                defaults.openai_use_responses_api,
            ),
            embedding_provider=source.get(
                "EMBEDDING_PROVIDER", defaults.embedding_provider
            ),
            embedding_model_name=source.get(
                "EMBEDDING_MODEL_NAME", defaults.embedding_model_name
            ),
            embedding_dimensions=int(
                source.get("EMBEDDING_DIMENSIONS", defaults.embedding_dimensions)
            ),
            embedding_batch_size=int(
                source.get("EMBEDDING_BATCH_SIZE", defaults.embedding_batch_size)
            ),
            qdrant_url=source.get("QDRANT_URL", defaults.qdrant_url),
            qdrant_api_key=source.get("QDRANT_API_KEY", defaults.qdrant_api_key),
            qdrant_collection_name=source.get(
                "GRAPH_RAG_QDRANT_COLLECTION", defaults.qdrant_collection_name
            ),
            neo4j_uri=source.get("NEO4J_URI", defaults.neo4j_uri),
            neo4j_username=source.get("NEO4J_USERNAME", defaults.neo4j_username),
            neo4j_password=source.get("NEO4J_PASSWORD", defaults.neo4j_password),
            neo4j_database=source.get("NEO4J_DATABASE", defaults.neo4j_database),
            max_search_results=int(
                source.get("AGENT_MAX_SEARCH_RESULTS", defaults.max_search_results)
            ),
            max_graph_depth=int(
                source.get("AGENT_MAX_GRAPH_DEPTH", defaults.max_graph_depth)
            ),
            max_graph_results=int(
                source.get("AGENT_MAX_GRAPH_RESULTS", defaults.max_graph_results)
            ),
            max_tool_calls=int(
                source.get("AGENT_MAX_TOOL_CALLS", defaults.max_tool_calls)
            ),
            recursion_limit=int(
                source.get("AGENT_RECURSION_LIMIT", defaults.recursion_limit)
            ),
            max_evidence_chars=int(
                source.get("AGENT_MAX_EVIDENCE_CHARS", defaults.max_evidence_chars)
            ),
            max_question_chars=int(
                source.get("AGENT_MAX_QUESTION_CHARS", defaults.max_question_chars)
            ),
            max_history_messages=int(
                source.get("AGENT_MAX_HISTORY_MESSAGES", defaults.max_history_messages)
            ),
        )
