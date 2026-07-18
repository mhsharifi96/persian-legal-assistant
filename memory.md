# Project Memory

Use this file as persistent project context for future Codex sessions. Update it when major architecture decisions, phase status, or operating assumptions change.

## Current Status

- Repository: `persian-legal-assistant`
- Main branch: `main`
- Remote: `git@github.com:mhsharifi96/persian-legal-assistant.git`
- Real AI/RAG providers implemented 2026-07-18: `OpenAILLM` (`ChatOpenAI`) and `OpenAIEmbeddingModel` (`OpenAIEmbeddings`) through LangChain; Qdrant vector persistence/search with LangChain-compatible payloads; `Neo4jGraphRepository` through `langchain-neo4j`; explicit source chunk→entity links for real graph expansion; opt-in LangSmith tracing with privacy masking; and Qdrant/Neo4j Compose services. Provider selection remains env-driven and fake/in-memory defaults remain unit-test safe.
- Phase 4 (admin UI + API + web frontend) implemented and verified 2026-07-08: Django 5.2 + DRF admin/API over a real database (Django ORM adapters), plus a Next.js 14 (App Router, TS, Tailwind) RTL/Persian web frontend consuming the API. Backend: new write ports (`LawyerWriteRepository`, `DocumentStore`, `EvaluationWriteRepository`) in `application/ports.py`; env-driven provider fields + `LAWYER_REPO_BUILDERS`/`DOCUMENT_STORE_BUILDERS`/`EVALUATION_REPO_BUILDERS` in `bootstrap.py` (memory/jsonl/orm); Django app `legal_assistant.infrastructure.orm` (models `LawyerRow`/`LegalDocumentRow`/`LegalChunkRow`/`EvaluationRecordRow` with full hierarchy metadata, domain↔ORM adapters in `repositories.py`, admin, `import_lawyers` management command, migration `0001_initial`); top-level Django project `config/` (+ `manage.py`) with `src` added to sys.path; `legal_assistant.interfaces.api` (container wiring, serializers, views, urls) exposing `/api/{health,lawyers,lawyers/recommend,lawyers/<id>,documents,chunks,evaluations,evaluations/run,ask}`. Writes require admin auth; reads/business endpoints are public; `/ask` runs the agentic graph and can be forced to refuse the fake LLM via `API_REQUIRE_REAL_LLM`. Frontend under `web/`: typed API client, four pages (lawyers/documents/evaluations/ask), `/api/ask` BFF proxy, SEO (`sitemap.ts`/`robots.ts`, real-data `generateMetadata`, `fa_IR`, `noindex` on ask/evaluations), self-hosted Vazirmatn. Verified end-to-end: DRF client exercised all endpoints against the real ORM DB; `next build` clean; live Django+Next stack renders real lawyer data via SSR. 42 unit tests still pass; `pyrefly check` clean (Django/DRF layers excluded via `project-excludes`). Real Qdrant/Neo4j/HuggingFace/LlamaParse/LLM adapters and a real lawyer/legal dataset import remain outstanding.
- Current implementation status: Phases 1, 2, and 3 have test-safe fake adapters, while OpenAI, Qdrant, and Neo4j now have real infrastructure adapters. Phase 3 adds `LawyerRecommendationService` (weighted semantic+success+location score, configurable weights, Persian rationale), `application/evaluation/` (`LegalAnswerEvaluator` + `EvaluationService` with LLM-judge metrics through `LLMPort`, deterministic citation grounding, stdlib aggregation, pandas-free `to_records()`), filled `LawyerRepository`/`EvaluationRepository` ports, in-memory + JSONL repositories, and bootstrap builders. A real parser/ingestion command and real datasets remain outstanding.
- (historical) Phase 1 and Phase 2 detail: Phase 1: domain models, application ports, fake adapters, Persian legal hierarchical chunking, ingestion service with per-chunk error isolation, graph extraction validation, RRF hybrid retrieval, env-driven `Settings.from_env()`, provider-registry `bootstrap.py`. Phase 2: dependency-free typed reasoning graph in `application/agentic/` (`AgentState`, router/decomposer/judge/`PersianAnswerGenerator` behind Protocols, `LegalQAGraph` with bounded self-reflection loop, chunk_id citation grounding, concurrent subquery retrieval via a single ThreadPoolExecutor boundary), `Citation` domain model, optional `CrewAnalysisPort`, `TaggedFakeLLM`, and `build_agentic_graph` wiring. 29 unit tests passing; `pyrefly check` clean. External provider adapters (real Qdrant, Neo4j, HuggingFace, LlamaParse, OpenAI/LLM) are still not implemented.
- Key Phase 2 decisions: (1) No LangGraph dependency — the core stays vendor-independent (`dependencies = []`); a future LangGraph adapter can wrap the node functions. (2) Ports kept synchronous; concurrency confined to `retrieval_node`'s thread pool rather than an async rewrite of Phase 1.
- Recommended next implementation step: implement the first real infrastructure adapter (e.g. `HuggingFaceEmbeddingModel` behind `EMBEDDING_PROVIDER=hf` or a real `LLMPort` behind `LLM_PROVIDER`) and register it in the corresponding `*_BUILDERS` registry, or begin Phase 3 (lawyer recommendation + RAGAS-style evaluation).

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
- `$persian-legal-admin-api`
- `$persian-legal-nextjs-ui`
- `$persian-legal-lawyer-fetcher`

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

Status: core foundation complete against fake in-memory adapters; real provider adapters (Qdrant, Neo4j, HuggingFace, LlamaParse) still pending. Persian legal hierarchical chunking, ingestion orchestration, graph extraction validation, and hybrid retriever foundation have been added, plus:

- Recursive splitting for articles/notes exceeding a token budget, preserving hierarchy metadata and adding `part_index`/`part_count`.
- Reciprocal Rank Fusion in `HybridRetriever` (vector and graph scores are not comparable and must not be sorted together as raw values) with a configurable graph fan-out cap.
- Structured `IngestionErrorRecord`s with per-chunk isolation for both embedding batch failures and graph extraction failures (a single bad chunk no longer aborts the whole document).
- Graph extraction repair prompts now include the specific validation error, not just the raw prior response.
- `Settings.from_env()` for env-driven configuration and a provider-registry pattern in `bootstrap.py`.

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

Status: implemented against fake ports. Dependency-free typed state machine (`application/agentic/`) with router → decompose → retrieve → judge → generate, bounded retry loop with limited-answer fallback, chunk_id-grounded citations, formal Persian answer template, concurrent subquery retrieval (thread pool), optional CrewAI adapter hook, and checkpoint hook. Real LLM adapter still pending (LLM_BUILDERS currently only has `fake`).

Goal:

- build LangGraph state machine;
- route intent;
- decompose questions;
- retrieve context;
- judge legal sufficiency;
- loop for re-retrieval when needed;
- generate formal Persian citation-grounded answers.

### Phase 3: Recommendation and Evaluation

Status: implemented against fake ports/repositories. `LawyerRecommendationService` (transparent weighted score, deterministic tie-breaking, Persian rationale) and `application/evaluation/` (context_precision/faithfulness/answer_relevancy/jurisdiction via injected judge `LLMPort`, deterministic citation grounding, stdlib aggregation + Persian summary + `to_records()`). In-memory and JSONL repositories provided; a real SQL/API/Pandas lawyer repo and a real judge LLM adapter are still pending.

Goal:

- recommend lawyers using semantic and structured scores;
- run RAGAS-style evaluation;
- report context precision, faithfulness, answer relevancy, and citation/legal grounding.

## Open Decisions

- Python dependency manager: undecided (pip + pyproject extras `[dev]`/`[api]` in use).
- Django project name: decided — top-level package `config` (settings module `config.settings`), app label `legal_orm`.
- API framework style: decided — Django + Django REST Framework (Django admin as the admin UI, DRF for the JSON API, Django ORM as the real persistence adapter). See `$persian-legal-admin-api`. Implementation not yet started.
- Background jobs: Celery/RQ not needed until ingestion jobs exist.
- Real LLM provider: OpenAI through LangChain (`LLM_PROVIDER=openai`), model configurable.
- Initial legal dataset source: undecided.

## Do Not Do

- Do not hard-code API keys or provider credentials.
- Do not commit `.env`, model caches, downloaded datasets, or database volumes.
- Do not place Qdrant, Neo4j, OpenAI, HuggingFace, LlamaParse, RAGAS, or CrewAI imports inside domain or application logic.
- Do not skip golden tests for Persian legal chunking.
