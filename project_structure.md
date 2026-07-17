# Project Structure

This document describes the intended repository structure for the Persian Legal Assistant. Use it as a guide when creating or reviewing files.

## Current Root Files

```text
.
├── AGENT.md
├── README.md
├── memory.md
├── project_structure.md
├── .gitignore
└── persian-legal-assistant-codex-skills/
```

## Intended Application Layout

Prefer this layout unless a later architectural decision replaces it:

```text
.
├── manage.py
├── pyproject.toml
├── requirements/
│   ├── base.txt
│   ├── dev.txt
│   └── integration.txt
├── config/
│   ├── __init__.py
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── local.py
│   │   └── test.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── src/
│   └── legal_assistant/
│       ├── domain/
│       ├── application/
│       ├── infrastructure/
│       ├── interfaces/
│       └── config/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── docker-compose.yml
├── Dockerfile
├── .dockerignore
└── .env.example
```

If the project uses a different package manager or Django layout, keep the same boundaries even if paths differ.

## Layer Responsibilities

### `domain/`

Pure business objects and legal concepts.

Allowed:

- dataclasses or Pydantic models;
- value objects;
- domain errors;
- legal hierarchy models;
- citation models.

Not allowed:

- Django ORM;
- Qdrant/Neo4j clients;
- OpenAI/HuggingFace/LlamaParse/RAGAS imports;
- environment variable reads.

### `application/`

Use cases, services, and abstract ports.

Expected files:

```text
application/
├── ports.py
├── services/
└── use_cases/
```

This layer defines contracts such as:

- `DocumentParserPort`
- `LegalChunkerPort`
- `EmbeddingModelPort`
- `VectorStoreRepository`
- `GraphRepository`
- `LLMPort`
- `HybridRetrieverPort`
- `LawyerRepository`
- `EvaluationRepository`

### `infrastructure/`

Concrete adapters for external tools.

Expected folders:

```text
infrastructure/
├── parsers/
├── embeddings/
├── vectorstores/
├── graphstores/
├── llms/
├── checkpoints/
├── evaluation/
└── repositories/
```

Examples:

- `LlamaParseDocumentParser`
- `HuggingFaceEmbeddingModel`
- `QdrantVectorStoreRepository`
- `Neo4jGraphRepository`
- `OpenAILLM`
- `RagasEvaluationRepository`
- `PandasLawyerRepository`

### `interfaces/`

Entry points into the application.

Expected folders:

```text
interfaces/
├── api/
├── cli/
└── management/
```

Django views, DRF serializers, management commands, and CLI wrappers belong here. They should call application services rather than vendor SDKs directly.

### `config/`

Project settings and dependency wiring.

Expected responsibilities:

- read typed settings;
- build concrete adapters;
- wire application services;
- keep provider selection configurable.

## Test Layout

```text
tests/
├── unit/
│   ├── test_chunking.py
│   ├── test_hybrid_retriever.py
│   └── test_agentic_core.py
├── integration/
│   ├── test_qdrant_repository.py
│   ├── test_neo4j_repository.py
│   └── test_docker_stack.py
└── fixtures/
    └── legal_texts/
```

Unit tests should use fake ports and must not require live services.

Integration tests may require Docker Compose and should be marked explicitly.

## Docker Layout

When Docker support is added, use `$persian-legal-docker-runtime`.

Expected files:

```text
Dockerfile
docker-compose.yml
docker-compose.override.yml
.dockerignore
.env.example
```

Expected service names:

```text
web
worker
postgres
redis
qdrant
neo4j
```

Only add `worker` and `redis` once background jobs are implemented.

## Skill Layout

Project-local skills live here:

```text
persian-legal-assistant-codex-skills/
├── persian-legal-architecture/
├── persian-legal-graphrag-ingestion/
├── persian-legal-agentic-core/
├── persian-legal-evaluation-recommender/
├── persian-legal-docker-runtime/
├── persian-legal-admin-api/
├── persian-legal-nextjs-ui/
└── persian-legal-lawyer-fetcher/
```

Each skill should contain:

```text
SKILL.md
agents/openai.yaml
references/
```

Do not add README files inside individual skill folders unless there is a strong reason; put detailed guidance in `references/`.

## Naming Conventions

- Python package: `legal_assistant`
- Django project package: `config`
- Tests: `test_*.py`
- Ports: suffix with `Port` or `Repository`
- Adapters: prefix with provider name, for example `QdrantVectorStoreRepository`
- Legal hierarchy fields: `book`, `bab`, `fasl`, `article_number`, `note_number`
