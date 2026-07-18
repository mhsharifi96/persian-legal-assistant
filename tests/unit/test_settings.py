from legal_assistant.config.settings import Settings


def test_settings_from_env_uses_defaults_when_unset() -> None:
    assert Settings.from_env({}) == Settings()


def test_settings_from_env_overrides_from_mapping() -> None:
    settings = Settings.from_env(
        {
            "EMBEDDING_PROVIDER": "hf",
            "EMBEDDING_MODEL_NAME": "some/model",
            "EMBEDDING_DIMENSIONS": "1024",
            "LLM_PROVIDER": "openai",
            "LLM_MODEL_NAME": "gpt-test",
            "QDRANT_COLLECTION_NAME": "legal-test",
            "NEO4J_DATABASE": "legal",
            "GRAPH_DEPTH": "3",
            "GRAPH_FANOUT_LIMIT": "10",
            "RRF_K": "30",
        }
    )

    assert settings.embedding_provider == "hf"
    assert settings.embedding_model_name == "some/model"
    assert settings.embedding_dimensions == 1024
    assert settings.llm_provider == "openai"
    assert settings.llm_model_name == "gpt-test"
    assert settings.qdrant_collection_name == "legal-test"
    assert settings.neo4j_database == "legal"
    assert settings.graph_depth == 3
    assert settings.graph_fanout_limit == 10
    assert settings.rrf_k == 30
