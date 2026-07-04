# Change Log

Use this file to record meaningful project-level changes. Keep entries short, dated, and useful for future agents.

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

