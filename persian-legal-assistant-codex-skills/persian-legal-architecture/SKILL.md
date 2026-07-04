---
name: persian-legal-architecture
description: Design and maintain the extensible architecture for a Persian LegalTech LLM system. Use when implementing or reviewing repository, port, adapter, service, configuration, dependency-injection, or test structure for a Persian legal assistant, Agentic RAG, GraphRAG, embedding, vector database, Neo4j, LLM, LangGraph, lawyer recommendation, or RAGAS evaluation codebase.
---

# Persian Legal Architecture

## Overview

Use this skill to keep the thesis codebase replaceable at the edges and stable in the core. The goal is that changing an embedding model, LLM provider, parser, vector database, graph database, orchestration framework, or evaluator does not require changes to domain objects or use cases.

## Core Rule

Implement every external capability behind an application port and one or more infrastructure adapters.

- Domain and application code may import only standard library, internal domain/application modules, and abstract ports.
- Infrastructure adapters may import external SDKs: HuggingFace, LlamaParse, Qdrant, Neo4j, OpenAI, LangGraph, CrewAI, RAGAS, Pandas.
- UI, CLI, FastAPI, notebooks, and scripts must call application services, not vendor SDKs directly.
- Dependency wiring belongs in config/bootstrap modules.

## Expected Package Shape

Prefer this shape unless the existing repository already has a clear equivalent:

```text
src/legal_assistant/
  domain/
    models.py
    value_objects.py
    errors.py
  application/
    ports.py
    services/
    use_cases/
  infrastructure/
    parsers/
    embeddings/
    vectorstores/
    graphstores/
    llms/
    checkpoints/
    evaluation/
    repositories/
  interfaces/
    api/
    cli/
  config/
    settings.py
    bootstrap.py
tests/
  unit/
  integration/
```

If an existing codebase uses different names, keep local conventions but preserve the dependency direction.

## Required Ports

Define or reuse ports for:

- `DocumentParserPort`
- `LegalChunkerPort`
- `EmbeddingModelPort`
- `VectorStoreRepository`
- `GraphRepository`
- `LLMPort`
- `HybridRetrieverPort`
- `CheckpointRepository`
- `LawyerRepository`
- `EvaluationRepository`

Read `references/ports-and-adapters.md` before implementing or refactoring these contracts.

## Implementation Workflow

1. Inspect the repository layout and existing abstractions before adding files.
2. Identify which external dependency is being introduced or changed.
3. Add or update the application port first.
4. Implement the concrete adapter under `infrastructure/`.
5. Wire the adapter through settings/bootstrap.
6. Add unit tests against the port contract using fake adapters.
7. Add integration tests only where external services are involved and make them opt-in.

## Configuration

Use typed settings for provider selection. Do not hard-code model names, collection names, Neo4j labels, OpenAI model names, API keys, or database URLs inside services.

Example setting names:

```text
EMBEDDING_PROVIDER=hf
EMBEDDING_MODEL_NAME=MCINext/Hakim-small
VECTORSTORE_PROVIDER=qdrant
GRAPHSTORE_PROVIDER=neo4j
LLM_PROVIDER=openai
LEGAL_JURISDICTION=IR
```

## Acceptance Checks

- Replacing `MCINext/Hakim-small` with another embedding model changes only settings or an embedding adapter.
- Replacing Qdrant or Neo4j does not alter use case code.
- Prompt templates and LLM model names are outside core business logic.
- Tests can run without live external services by using fake adapters.
- Persian legal terms, hierarchy metadata, citations, and jurisdiction fields are preserved through all layers.

## Thesis Context

The target system is a Persian legal question-answering assistant for Iranian law. It combines RAG, Agentic RAG, autonomous agents, legal document retrieval, citation-grounded Persian answers, lawyer recommendation, and evaluation for hallucination reduction.
