from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


def _env_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    jurisdiction: str = "IR"
    embedding_provider: str = "fake"
    embedding_model_name: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072
    vectorstore_provider: str = "memory"
    graphstore_provider: str = "memory"
    parser_provider: str = "fake"
    llm_provider: str = "fake"
    llm_model_name: str = "gpt-5.6"
    openai_api_key: str = ""
    openai_api_base: str = ""
    openai_timeout_seconds: float = 60.0
    openai_max_retries: int = 2
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection_name: str = "persian_legal_chunks"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"
    graph_depth: int = 1
    graph_fanout_limit: int = 20
    rrf_k: int = 60
    max_chunk_tokens: int = 400
    chunk_overlap_tokens: int = 40
    embedding_batch_size: int = 64
    # Phase 2 agentic core
    agent_max_retries: int = 2
    agent_retrieval_top_k: int = 8
    agent_max_context_tokens: int = 2000
    agent_retrieval_max_workers: int = 4
    # Phase 3 recommendation and evaluation
    rec_semantic_weight: float = 0.5
    rec_success_weight: float = 0.3
    rec_location_weight: float = 0.2
    rec_top_n: int = 5
    eval_failure_threshold: float = 0.5
    # Admin/API persistence providers. Defaults are test-safe (in-memory); the
    # Django/API deployment profile sets these to "orm" via environment so the
    # delivered app runs on the real database. See persian-legal-admin-api.
    lawyer_repo_provider: str = "memory"
    evaluation_repo_provider: str = "memory"
    document_store_provider: str = "memory"
    lawyer_data_path: str = ""
    evaluation_data_path: str = ""
    # When true, the /ask API refuses to answer with a fake LLM provider instead
    # of returning a non-real answer (production profile).
    api_require_real_llm: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Build Settings from environment variables, falling back to the
        dataclass defaults for anything unset. Pass an explicit ``env`` mapping
        in tests instead of mutating ``os.environ``."""
        source = env if env is not None else os.environ
        defaults = cls()
        return cls(
            jurisdiction=source.get("LEGAL_JURISDICTION", defaults.jurisdiction),
            embedding_provider=source.get("EMBEDDING_PROVIDER", defaults.embedding_provider),
            embedding_model_name=source.get(
                "EMBEDDING_MODEL_NAME", defaults.embedding_model_name
            ),
            embedding_dimensions=int(
                source.get("EMBEDDING_DIMENSIONS", defaults.embedding_dimensions)
            ),
            vectorstore_provider=source.get(
                "VECTORSTORE_PROVIDER", defaults.vectorstore_provider
            ),
            graphstore_provider=source.get(
                "GRAPHSTORE_PROVIDER", defaults.graphstore_provider
            ),
            parser_provider=source.get("PARSER_PROVIDER", defaults.parser_provider),
            llm_provider=source.get("LLM_PROVIDER", defaults.llm_provider),
            llm_model_name=source.get("LLM_MODEL_NAME", defaults.llm_model_name),
            openai_api_key=source.get("OPENAI_API_KEY", defaults.openai_api_key),
            openai_api_base=source.get("OPENAI_API_BASE", defaults.openai_api_base),
            openai_timeout_seconds=float(
                source.get("OPENAI_TIMEOUT_SECONDS", defaults.openai_timeout_seconds)
            ),
            openai_max_retries=int(
                source.get("OPENAI_MAX_RETRIES", defaults.openai_max_retries)
            ),
            qdrant_url=source.get("QDRANT_URL", defaults.qdrant_url),
            qdrant_api_key=source.get("QDRANT_API_KEY", defaults.qdrant_api_key),
            qdrant_collection_name=source.get(
                "QDRANT_COLLECTION_NAME", defaults.qdrant_collection_name
            ),
            neo4j_uri=source.get("NEO4J_URI", defaults.neo4j_uri),
            neo4j_username=source.get("NEO4J_USERNAME", defaults.neo4j_username),
            neo4j_password=source.get("NEO4J_PASSWORD", defaults.neo4j_password),
            neo4j_database=source.get("NEO4J_DATABASE", defaults.neo4j_database),
            graph_depth=int(source.get("GRAPH_DEPTH", defaults.graph_depth)),
            graph_fanout_limit=int(
                source.get("GRAPH_FANOUT_LIMIT", defaults.graph_fanout_limit)
            ),
            rrf_k=int(source.get("RRF_K", defaults.rrf_k)),
            max_chunk_tokens=int(source.get("MAX_CHUNK_TOKENS", defaults.max_chunk_tokens)),
            chunk_overlap_tokens=int(
                source.get("CHUNK_OVERLAP_TOKENS", defaults.chunk_overlap_tokens)
            ),
            embedding_batch_size=int(
                source.get("EMBEDDING_BATCH_SIZE", defaults.embedding_batch_size)
            ),
            agent_max_retries=int(
                source.get("AGENT_MAX_RETRIES", defaults.agent_max_retries)
            ),
            agent_retrieval_top_k=int(
                source.get("AGENT_RETRIEVAL_TOP_K", defaults.agent_retrieval_top_k)
            ),
            agent_max_context_tokens=int(
                source.get(
                    "AGENT_MAX_CONTEXT_TOKENS", defaults.agent_max_context_tokens
                )
            ),
            agent_retrieval_max_workers=int(
                source.get(
                    "AGENT_RETRIEVAL_MAX_WORKERS", defaults.agent_retrieval_max_workers
                )
            ),
            rec_semantic_weight=float(
                source.get("REC_SEMANTIC_WEIGHT", defaults.rec_semantic_weight)
            ),
            rec_success_weight=float(
                source.get("REC_SUCCESS_WEIGHT", defaults.rec_success_weight)
            ),
            rec_location_weight=float(
                source.get("REC_LOCATION_WEIGHT", defaults.rec_location_weight)
            ),
            rec_top_n=int(source.get("REC_TOP_N", defaults.rec_top_n)),
            eval_failure_threshold=float(
                source.get("EVAL_FAILURE_THRESHOLD", defaults.eval_failure_threshold)
            ),
            lawyer_repo_provider=source.get(
                "LAWYER_REPO_PROVIDER", defaults.lawyer_repo_provider
            ),
            evaluation_repo_provider=source.get(
                "EVALUATION_REPO_PROVIDER", defaults.evaluation_repo_provider
            ),
            document_store_provider=source.get(
                "DOCUMENT_STORE_PROVIDER", defaults.document_store_provider
            ),
            lawyer_data_path=source.get("LAWYER_DATA_PATH", defaults.lawyer_data_path),
            evaluation_data_path=source.get(
                "EVALUATION_DATA_PATH", defaults.evaluation_data_path
            ),
            api_require_real_llm=_env_bool(
                source.get("API_REQUIRE_REAL_LLM"), defaults.api_require_real_llm
            ),
        )
