from dataclasses import dataclass


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
