# Project Memory

Use this file as persistent project context for future Codex sessions. Update it when major architecture decisions, phase status, or operating assumptions change.

## Current Status

- Repository: `persian-legal-assistant`
- Main branch: `main`
- Remote: `git@github.com:mhsharifi96/persian-legal-assistant.git`
- Current implementation status: initial Python package foundation is in place with domain models, application ports, fake adapters, Persian legal hierarchical chunking, ingestion service, graph extraction validation, hybrid retrieval, and unit tests. External provider adapters are not implemented yet.
- Recommended next implementation step: install test dependencies and continue Phase 1 with real provider adapters behind the existing ports.

## Project Goal

Build a Persian Legal Assistant for Iranian law based on LLMs, RAG, Agentic RAG, legal document retrieval, citation-grounded Persian answers, lawyer recommendation, and hallucination-focused evaluation.

## Core Engineering Decision

The codebase must use ports/adapters so provider changes do not rewrite the core.

Changing these should only require configuration or infrastructure adapter changes:

- embedding model;
- parser provider;
- vector database;
- graph database;
- LLM provider;
- judge/evaluation backend;
- lawyer repository;
- Docker runtime services.

## Local Skills

Always inspect local project skills before major work:

```text
persian-legal-assistant-codex-skills/
```

Current skills:

- `$persian-legal-architecture`
- `$persian-legal-graphrag-ingestion`
- `$persian-legal-agentic-core`
- `$persian-legal-evaluation-recommender`
- `$persian-legal-docker-runtime`

## Suggested Next Prompt

Use this prompt to start coding:

```text
Read AGENT.md, memory.md, project_structure.md, and the local skills.
Use $persian-legal-architecture.
Create the initial Python/Django project architecture.
Define domain models, application ports, fake adapters, settings, bootstrap wiring, and tests.
Do not implement real Qdrant, Neo4j, OpenAI, HuggingFace, or LlamaParse calls yet.
```

## Phase Plan

### Phase 0: Foundation

Status: started. Initial src/legal_assistant package, domain models, application ports, fake adapters, settings/bootstrap, and tests have been added.

Goal:

- create Python/Django project structure;
- define domain models and application ports;
- add fake adapters;
- add tests;
- add settings/bootstrap;
- keep external SDKs out of domain/application.

### Phase 1: GraphRAG Ingestion

Status: started. Persian legal hierarchical chunking, ingestion orchestration, graph extraction validation, and hybrid retriever foundation have been added with fake in-memory adapters.

Goal:

- parse Iranian legal PDFs/documents;
- chunk by Persian legal hierarchy;
- preserve legal metadata;
- embed chunks;
- store vectors;
- extract graph entities/relations;
- store graph;
- expose hybrid retriever.

Minimum hierarchy:

```text
کتاب، باب، فصل، ماده، تبصره
```

### Phase 2: Agentic Core

Status: not started.

Goal:

- build LangGraph state machine;
- route intent;
- decompose questions;
- retrieve context;
- judge legal sufficiency;
- loop for re-retrieval when needed;
- generate formal Persian citation-grounded answers.

### Phase 3: Recommendation and Evaluation

Status: not started.

Goal:

- recommend lawyers using semantic and structured scores;
- run RAGAS-style evaluation;
- report context precision, faithfulness, answer relevancy, and citation/legal grounding.

## Open Decisions

- Python dependency manager: undecided.
- Django project name: undecided.
- API framework style: Django views vs DRF vs FastAPI sidecar, undecided.
- Background jobs: Celery/RQ not needed until ingestion jobs exist.
- Real LLM provider: undecided.
- Initial legal dataset source: undecided.

## Do Not Do

- Do not hard-code API keys or provider credentials.
- Do not commit `.env`, model caches, downloaded datasets, or database volumes.
- Do not place Qdrant, Neo4j, OpenAI, HuggingFace, LlamaParse, RAGAS, or CrewAI imports inside domain or application logic.
- Do not skip golden tests for Persian legal chunking.

