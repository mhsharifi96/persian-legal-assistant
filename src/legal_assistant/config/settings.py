from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    jurisdiction: str = "IR"
    embedding_provider: str = "fake"
    embedding_model_name: str = "MCINext/Hakim-small"
    vectorstore_provider: str = "memory"
    graphstore_provider: str = "memory"
    parser_provider: str = "fake"
    llm_provider: str = "fake"
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
            vectorstore_provider=source.get(
                "VECTORSTORE_PROVIDER", defaults.vectorstore_provider
            ),
            graphstore_provider=source.get(
                "GRAPHSTORE_PROVIDER", defaults.graphstore_provider
            ),
            parser_provider=source.get("PARSER_PROVIDER", defaults.parser_provider),
            llm_provider=source.get("LLM_PROVIDER", defaults.llm_provider),
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
        )
