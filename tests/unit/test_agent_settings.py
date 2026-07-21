from __future__ import annotations

import pytest

from legal_assistant.config.settings import AgentSettings


def test_agent_settings_parse_environment() -> None:
    settings = AgentSettings.from_env(
        {
            "AGENT_MODEL_NAME": "gpt-test",
            "AGENT_MAX_TOOL_CALLS": "3",
            "AGENT_MAX_GRAPH_DEPTH": "1",
            "OPENAI_USE_RESPONSES_API": "true",
            "GRAPH_RAG_QDRANT_COLLECTION": "graph-test",
        }
    )

    assert settings.model_name == "gpt-test"
    assert settings.max_tool_calls == 3
    assert settings.max_graph_depth == 1
    assert settings.openai_use_responses_api is True
    assert settings.qdrant_collection_name == "graph-test"


def test_agent_settings_reject_non_positive_limits() -> None:
    with pytest.raises(ValueError, match="max_tool_calls"):
        AgentSettings(max_tool_calls=0)
