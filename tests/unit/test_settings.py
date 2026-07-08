from legal_assistant.config.settings import Settings


def test_settings_from_env_uses_defaults_when_unset() -> None:
    assert Settings.from_env({}) == Settings()


def test_settings_from_env_overrides_from_mapping() -> None:
    settings = Settings.from_env(
        {
            "EMBEDDING_PROVIDER": "hf",
            "EMBEDDING_MODEL_NAME": "some/model",
            "GRAPH_DEPTH": "3",
            "GRAPH_FANOUT_LIMIT": "10",
            "RRF_K": "30",
        }
    )

    assert settings.embedding_provider == "hf"
    assert settings.embedding_model_name == "some/model"
    assert settings.graph_depth == 3
    assert settings.graph_fanout_limit == 10
    assert settings.rrf_k == 30
