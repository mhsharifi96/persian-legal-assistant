# Change Log

Use this file to record meaningful project-level changes. Keep entries short, dated, and useful for future agents.

## 2026-07-08

### Phase 3 Recommendation and Evaluation

- Lawyer recommendation: `LawyerRecommendationService` over `LawyerRepository` + `EmbeddingModelPort` with a transparent, configurable weighted score (`semantic_weight*cosine + success_weight*success + location_weight*location_match`), deterministic tie-breaking (score → success → id), Persian rationale, and Persian-digit-normalized location matching. Documented as a practical approximation, not AGE-MOEA.
- RAGAS-style evaluation (`application/evaluation/`): `LegalAnswerEvaluator` scores context_precision, faithfulness, answer_relevancy, and a jurisdiction aspect critic via an injected Persian-capable judge `LLMPort` (provider not hard-coded), plus a deterministic citation-grounding critic. `EvaluationService` aggregates mean/median/min/failure-counts with stdlib `statistics`, ranks worst examples by faithfulness/context-precision, and emits a Persian summary. Kept pandas-free per architecture rules; `EvaluationReport.to_records()` returns DataFrame-ready rows (metadata columns prefixed `meta_` to avoid colliding with metric names).
- Ports/models: filled `LawyerRepository.list_lawyers` and `EvaluationRepository.load_records`; added `LawyerProfile`, `LawyerRecommendation`, `EvaluationRecord` domain models.
- Adapters/wiring: `InMemoryLawyerRepository`/`InMemoryEvaluationRepository` fakes, file-backed `JsonlLawyerRepository`/`JsonlEvaluationRepository` (percent→0..1 success normalization, specialty splitting), `Settings` weight/threshold knobs, and `build_lawyer_recommendation_service`/`build_evaluation_service`/`build_recommendation_settings` bootstrap builders.
- Tests: 42 unit tests passing (13 new: scoring math, location/digit normalization, tie-breaking, top-n, specialty filter, citation grounding, report aggregation/worst-ranking, `to_records` column-collision guard, repository ports, JSONL loaders, bootstrap smoke); `pyrefly check` clean.

### Phase 2 Agentic Core

- Added a dependency-free, typed reasoning graph (`application/agentic/`): `AgentState`, `RouterDecision`, `JudgeVerdict`, and LLM-backed router/decomposer/judge/`PersianAnswerGenerator` components behind Protocols. No LangGraph/CrewAI/vendor import in the core; a future LangGraph adapter can wrap the same node functions.
- `LegalQAGraph` runs router → decompose → retrieve → judge with a bounded self-reflection loop (`agent_max_retries`); on retry exhaustion it emits a limited answer with an explicit Persian insufficiency warning. Non-legal intents (general_chat/out_of_scope/lawyer_recommendation) short-circuit before retrieval.
- Concurrency decision: ports kept synchronous (all of Phase 1 is sync); concurrent subquery retrieval is confined to a single `ThreadPoolExecutor` boundary in `retrieval_node`, the skill's sanctioned sync-via-thread-pool option. Context assembly deduplicates by `chunk_id` (keeping highest score) and enforces a token budget.
- Citations are grounded by `chunk_id`: `generation_node` only cites ids present in `retrieved_context`; hallucinated ids are dropped. Added `Citation` domain model and optional `CrewAnalysisPort`.
- Added `TaggedFakeLLM` (order-independent, per-task responses with sensible defaults), `FakeCrewAnalysis`, `InMemoryCheckpointRepository`; `Settings` agent knobs; and `build_llm`/`build_agentic_graph` bootstrap wiring.
- Tests: 29 unit tests passing (11 new agentic-core tests covering happy path, insufficient-context loop, max-retry fallback, general-chat/out-of-scope/handoff routes, citation grounding, context dedup, crew fold-in, checkpointing, bootstrap smoke); `pyrefly check` clean.

## 2026-07-07

### Phase 1 Hardening

- Chunker: recursive splitting for oversized `ماده`/`تبصره` text into token-budgeted subchunks with `part_index`/`part_count`, keeping full hierarchy metadata; added a golden test using noisy parser-like layout.
- `HybridRetriever`: replaced raw-score merge with Reciprocal Rank Fusion (vector and graph scores are not comparable) and added a configurable graph fan-out cap.
- Ingestion: added `IngestionErrorRecord` with per-chunk isolation for embedding-batch and graph-extraction failures, surfaced on `IngestionResult.errors` and an optional `IngestionErrorSink`; graph extraction repair prompts now include the specific validation error.
- Config: added `Settings.from_env()` for env-driven configuration and converted `bootstrap.py` to a provider-registry pattern (`EMBEDDING_BUILDERS`/`VECTORSTORE_BUILDERS`/`GRAPHSTORE_BUILDERS`).
- Updated the `persian-legal-graphrag-ingestion`, `persian-legal-architecture`, and `persian-legal-agentic-core` skill contracts to encode these lessons for future work.
- Tests: 18 unit tests passing; `pyrefly check` clean.

## 2026-07-04

### Initial Project Guidance

- Created initial repository documentation for the Persian Legal Assistant thesis project.
- Added `AGENT.md` with project instructions, architecture rules, implementation phases, testing expectations, and Docker guidance.
- Added `README.md` with usage instructions, suggested Codex prompts, local skill usage, roadmap, testing strategy, and skill maintenance guidance.
- Added `.gitignore` for Python/Django, secrets, virtual environments, local databases, model caches, datasets, Docker service state, and OS/editor noise.

### Local Codex Skills

- Added project-local skill package under `persian-legal-assistant-codex-skills/`.
- Added `$persian-legal-architecture` for ports/adapters, repositories, dependency injection, and replaceable provider architecture.
- Added `$persian-legal-graphrag-ingestion` for Phase 1 document parsing, Persian legal hierarchy chunking, Qdrant, Neo4j, knowledge graph extraction, and hybrid retrieval.
- Added `$persian-legal-agentic-core` for Phase 2 LangGraph reasoning, routing, query decomposition, retrieval, judge loop, optional CrewAI analysis, and citation-grounded Persian generation.
- Added `$persian-legal-evaluation-recommender` for Phase 3 lawyer recommendation and RAGAS-style evaluation.
- Added `$persian-legal-docker-runtime` for Dockerfile, Docker Compose, `.dockerignore`, `.env.example`, health checks, and local service orchestration.

### Agent Helper Files

- Added `memory.md` for persistent project context, phase status, open decisions, and suggested next prompt.
- Added `project_structure.md` for intended repository layout, layer responsibilities, test layout, Docker layout, skill layout, and naming conventions.
- Updated `AGENT.md` so future agents read `memory.md` and `project_structure.md` before major implementation work.

### Git

- Initial commit pushed to `origin/main`:

```text
a35cc4e Initial project guidance and Codex skills
```

## Update Rules

When adding a new entry:

- Use date heading `YYYY-MM-DD`.
- Group changes by area: architecture, Phase 1, Phase 2, Phase 3, Docker, docs, tests, skills.
- Mention important decisions and migrations.
- Do not include secrets, API keys, or private credentials.

