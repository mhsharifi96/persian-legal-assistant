# Ports and Adapters Contract

## Dependency Direction

Use this dependency direction:

```text
interfaces -> application -> domain
infrastructure -> application -> domain
config/bootstrap -> infrastructure + application
```

`domain` and `application` must not import vendor SDKs.

## Core Data Models

Use immutable or near-immutable data models for cross-layer data. Pydantic, dataclasses, or TypedDicts are all acceptable if consistent with the repository.

Recommended models:

```python
LegalDocument(id, title, source_uri, jurisdiction, document_type, effective_date, metadata)
LegalChunk(id, document_id, text, hierarchy, citations, metadata)
LegalHierarchy(book, bab, fasl, article, note)
RetrievedContext(chunk_id, text, score, source, hierarchy, citations, graph_neighbors)
GraphEntity(id, type, name, properties)
GraphRelation(source_id, target_id, type, properties)
LegalAnswer(text, citations, confidence, warnings)
```

## Port Sketch

```python
from typing import Protocol, Sequence

class DocumentParserPort(Protocol):
    def parse(self, source_uri: str) -> list[LegalDocument]: ...

class LegalChunkerPort(Protocol):
    def chunk(self, document: LegalDocument) -> list[LegalChunk]: ...

class EmbeddingModelPort(Protocol):
    @property
    def dimension(self) -> int: ...
    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...

class VectorStoreRepository(Protocol):
    def upsert_chunks(self, chunks: Sequence[LegalChunk], vectors: Sequence[list[float]]) -> None: ...
    def search(self, query_vector: list[float], *, filters: dict | None, top_k: int) -> list[RetrievedContext]: ...

class GraphRepository(Protocol):
    def upsert_entities(self, entities: Sequence[GraphEntity]) -> None: ...
    def upsert_relations(self, relations: Sequence[GraphRelation]) -> None: ...
    def expand_context(self, chunk_ids: Sequence[str], *, depth: int) -> list[RetrievedContext]: ...

class LLMPort(Protocol):
    def complete(self, messages: list[dict], *, response_schema: dict | None = None) -> str | dict: ...

class HybridRetrieverPort(Protocol):
    def retrieve(self, query: str, *, top_k: int = 8, filters: dict | None = None) -> list[RetrievedContext]: ...
```

## Repository Pattern

Use repositories for persistence and retrieval boundaries:

- `VectorStoreRepository`: Qdrant, later Milvus, Weaviate, pgvector, Elasticsearch.
- `GraphRepository`: Neo4j, later Memgraph, Kuzu, ArangoDB.
- `LawyerRepository`: mock Pandas dataset, later SQL, API, or CRM.
- `EvaluationRepository`: local JSONL/CSV, later experiment tracker.

Repositories return domain/application DTOs, not raw SDK responses.

## Adapter Naming

Name concrete adapters by provider:

```text
HuggingFaceEmbeddingModel
LlamaParseDocumentParser
QdrantVectorStoreRepository
Neo4jGraphRepository
OpenAILLM
LocalTransformersLLM
PandasLawyerRepository
RagasEvaluationRepository
```

## Configuration and Injection

Wire adapters in `config/bootstrap.py` or the local equivalent:

```python
def build_embedding_model(settings: Settings) -> EmbeddingModelPort:
    if settings.embedding_provider == "hf":
        return HuggingFaceEmbeddingModel(settings.embedding_model_name)
    raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")
```

Application services receive ports in constructors. Avoid global singletons except for explicitly managed app lifespan objects.

## Testing Rules

- Unit tests target application services with fake ports.
- Contract tests verify each adapter satisfies the port behavior.
- Integration tests use markers such as `@pytest.mark.integration` and read connection settings from environment variables.
- Golden tests are useful for Persian legal chunking. Store small representative law snippets with `کتاب`, `باب`, `فصل`, `ماده`, and `تبصره`.
