# Persian Legal Assistant

This repository is the main implementation workspace for a PhD thesis project:

**Design and evaluation of an intelligent Persian legal question-answering assistant based on large language models.**

The project target is a modular Persian LegalTech system for Iranian law. It will combine legal document ingestion, Agentic RAG, citation-grounded Persian answers, lawyer recommendation, and automated evaluation for hallucination and retrieval quality.

## Repository Status

Implemented so far (fake defaults plus opt-in real providers):

- **Phase 1 – GraphRAG ingestion**: Persian legal hierarchical chunking, OpenAI embeddings through LangChain, Qdrant vector search, Neo4j chunk-linked graph expansion, graph extraction, and RRF hybrid retrieval.
- **Phase 2 – Agentic core**: dependency-free reasoning graph (router → decompose → retrieve → judge → generate) with bounded self-reflection and citation grounding.
- **Phase 3 – Recommendation & evaluation**: weighted lawyer recommendation and RAGAS-style evaluation.
- **Admin UI + API**: Django 5 admin and a Django REST Framework API over a **real database** (Django ORM adapters).
- **Web frontend**: a Next.js 14 (App Router, TypeScript, Tailwind) RTL/Persian UI that consumes the API.
- **LLM + observability**: OpenAI chat through LangChain and opt-in LangSmith traces with configurable input/output masking.
- **Docker**: `web` (Django) + `postgres` + `qdrant` + `neo4j` + `web-ui` (Next.js) via Docker Compose.

Still outstanding: a real document parser, an ingestion command/job, and a real Iranian legal/lawyer dataset.

Important files and folders:

```text
AGENT.md                          project-level instructions for agents
memory.md                         persistent decisions and phase status
project_structure.md              intended layout and naming
src/legal_assistant/              domain, application, infrastructure, interfaces, config
config/ + manage.py               Django project (settings, urls, wsgi/asgi)
web/                              Next.js frontend
docker-compose.yml, Dockerfile    local runtime stack
persian-legal-assistant-codex-skills/   local implementation guides (skills)
```

## Requirements

- Python 3.11+ (the repo is developed on 3.12)
- Node.js 18.18+ and npm (for the web frontend)
- Docker + Docker Compose (recommended for Qdrant and Neo4j)

## Setup & Run — Docker (recommended)

Brings up the API/admin, Postgres, Qdrant, Neo4j, and the web UI together. Migrations run automatically on start.

```bash
cp .env.example .env          # set DJANGO_SECRET_KEY and OPENAI_API_KEY
docker compose up --build     # API :8008, UI :3008, Qdrant :6333, Neo4j :7474
```

If a host port is already taken, override it (host port only):

```bash
WEB_PORT=8020 UI_PORT=3020 DB_HOST_PORT=55432 QDRANT_HOST_PORT=6433 \
NEO4J_HTTP_HOST_PORT=7574 NEO4J_BOLT_HOST_PORT=7787 docker compose up --build
```

Create an admin user and (optionally) import real lawyer data:

```bash
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py import_lawyers /path/inside/container/lawyers.jsonl
```

- Admin UI: `http://localhost:8008/admin/`
- API root (health): `http://localhost:8008/api/health/`
- Web UI: `http://localhost:3008/`

Useful commands:

```bash
docker compose logs -f web
docker compose exec web python manage.py migrate
docker compose exec web pytest
docker compose down            # add -v to also drop the database volume
```

## Setup & Run — Local (without Docker)

### Backend (Django admin + DRF API)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[api,ai]'       # add ,postgres for Postgres: '.[api,postgres,ai]'

# Use the real database-backed repositories for the admin/API (defaults are
# test-safe in-memory; the app profile switches them to the ORM):
export LAWYER_REPO_PROVIDER=orm
export EVALUATION_REPO_PROVIDER=orm
export DOCUMENT_STORE_PROVIDER=orm

python manage.py migrate          # defaults to SQLite (db.sqlite3)
python manage.py createsuperuser
python manage.py runserver        # http://localhost:8000
```

Load real data (no fabricated rows ship with the app) via the admin, the API, or:

```bash
python manage.py import_lawyers path/to/your/lawyers.jsonl   # idempotent (upsert on lawyer_id)
```

Each JSON/JSONL record looks like:

```json
{"lawyer_id": "L-001", "full_name": "زهرا کریمی", "specialties": ["حقوق خانواده"], "location": "تهران", "success_rate": 0.82}
```

### Frontend (Next.js)

```bash
cd web
npm install
cp .env.example .env.local        # API_BASE_URL=http://localhost:8000
npm run dev                       # http://localhost:3000
```

## API Endpoints

Base path `/api/`. Reads and business actions are public; writes require an admin session.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health/` | Service + active provider status |
| GET / POST | `/api/lawyers/` | List / create lawyers (POST = admin) |
| GET / PUT / DELETE | `/api/lawyers/<id>/` | Retrieve / update / delete (write = admin) |
| POST | `/api/lawyers/recommend/` | Ranked lawyer recommendations + Persian rationale |
| GET | `/api/documents/`, `/api/chunks/` | Browse ingested documents / chunks |
| GET / POST | `/api/evaluations/` | List / add evaluation records (POST = admin) |
| POST | `/api/evaluations/run/` | Run RAGAS-style evaluation, return metrics |
| POST | `/api/ask/` | Agentic Persian answer with `chunk_id` citations |

`/api/ask/` runs the agentic graph. The safe code defaults use fake/in-memory providers; `.env.example` selects the real `openai`/`qdrant`/`neo4j` profile. To enable LangSmith, set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY`; legal prompt/response payloads are masked by default.

The real provider settings are:

```text
LLM_PROVIDER=openai
LLM_MODEL_NAME=gpt-5.6
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL_NAME=text-embedding-3-large
EMBEDDING_DIMENSIONS=3072
VECTORSTORE_PROVIDER=qdrant
GRAPHSTORE_PROVIDER=neo4j
```

## Tests & Checks

```bash
pytest                       # unit tests (fake ports, no live services)
pytest -m integration        # external-service tests (opt-in)
pyrefly check                # static type checking
cd web && npm run build      # frontend production build + type check
```

## How To Use This Project With Codex

Open this repository in Codex and start by asking Codex to read `AGENT.md` and the local skills.

Recommended first prompt:

```text
Read AGENT.md and the local skills in persian-legal-assistant-codex-skills.
Start with the architecture foundation only.

Create the initial Python/Django project structure for the Persian Legal Assistant.
Define domain models, application ports, settings, bootstrap wiring, and fake adapters.
Do not implement real Qdrant, Neo4j, OpenAI, HuggingFace, or LlamaParse calls yet.
Add unit tests for the fake adapters and application services.
```

After that, start Phase 1 in smaller steps:

```text
Use $persian-legal-graphrag-ingestion.
Implement only Persian legal hierarchical chunking.
It must recognize کتاب، باب، فصل، ماده، تبصره and preserve full hierarchy metadata.
Add golden unit tests with Persian legal sample text.
```

Then continue with real adapters:

```text
Continue Phase 1.
Add HuggingFace embedding adapter, Qdrant vector repository, Neo4j graph repository, and LLM graph extraction adapter.
Keep all implementations behind the ports already defined.
Add integration tests behind pytest markers.
```

## Local Skills

The local skills are project-specific implementation guides.

```text
persian-legal-assistant-codex-skills/
  persian-legal-architecture/
  persian-legal-graphrag-ingestion/
  persian-legal-agentic-core/
  persian-legal-evaluation-recommender/
  persian-legal-docker-runtime/
  persian-legal-admin-api/
  persian-legal-nextjs-ui/
  persian-legal-lawyer-fetcher/
```

Use them by name in prompts:

```text
Use $persian-legal-architecture to design the base architecture.
```

```text
Use $persian-legal-graphrag-ingestion to implement Phase 1 chunking and retrieval.
```

```text
Use $persian-legal-agentic-core to implement Phase 2 LangGraph reasoning.
```

```text
Use $persian-legal-evaluation-recommender to implement Phase 3 recommendation and evaluation.
```

```text
Use $persian-legal-docker-runtime to add or update Docker Compose support.
```

```text
Use $persian-legal-admin-api to build the Django admin UI and DRF API over real data.
```

```text
Use $persian-legal-nextjs-ui to build the Next.js RTL/Persian frontend over the API.
```

```text
Use $persian-legal-lawyer-fetcher to fetch public lawyer-directory records safely and normalize them for Django import.
```

## Development Principles

The main engineering requirement is replaceability.

Changing any of these must not require rewriting core use cases:

- embedding model, including replacing `MCINext/Hakim-small`;
- vector database, including replacing Qdrant;
- graph database, including replacing Neo4j;
- LLM provider or model;
- parser provider, including replacing LlamaParse;
- evaluation backend or judge LLM;
- lawyer data repository.

Use ports and adapters:

```text
interfaces -> application -> domain
infrastructure -> application -> domain
config/bootstrap -> infrastructure + application
```

External SDKs belong in `infrastructure/`, not in domain or application services.

## Suggested Implementation Roadmap

### Step 1: Architecture Foundation

Create the package structure, domain models, ports, fake adapters, settings, and tests.

Expected boundaries:

- `DocumentParserPort`
- `LegalChunkerPort`
- `EmbeddingModelPort`
- `VectorStoreRepository`
- `GraphRepository`
- `LLMPort`
- `HybridRetrieverPort`
- `LawyerRepository`
- `EvaluationRepository`

### Step 2: Phase 1 - GraphRAG Ingestion

Implement:

- legal document parsing boundary;
- hierarchical Persian legal chunking;
- embedding adapter;
- vector repository;
- graph extraction service;
- graph repository;
- hybrid retriever.

Every legal chunk must preserve:

```text
document_id, source_uri, jurisdiction, law_title, document_type,
book, bab, fasl, article_number, note_number,
effective_date, publication_date, version, page_start, page_end,
char_start, char_end, parser_name, chunking_strategy
```

### Step 3: Phase 2 - Agentic Core

Implement:

- LangGraph state;
- router node;
- query decomposition node;
- retrieval node;
- judge/verification node;
- optional CrewAI analysis adapter;
- generation node;
- bounded retry loop;
- memory/checkpointing.

Generated answers must be formal Persian and citation-grounded.

### Step 4: Phase 3 - Recommendation and Evaluation

Implement:

- lawyer repository;
- recommendation service;
- configurable scoring weights;
- evaluation dataset loader;
- RAGAS-style evaluation;
- Persian-capable judge LLM wrapper;
- summary report.

### Step 5: Docker Runtime

Use `$persian-legal-docker-runtime` when the project needs repeatable local runtime setup.

Implement:

- `Dockerfile`;
- `docker-compose.yml`;
- optional `docker-compose.override.yml`;
- `.dockerignore`;
- `.env.example`;
- service wiring for Django, Postgres, Redis, Qdrant, Neo4j, and optional workers.

Recommended prompt:

```text
Use $persian-legal-docker-runtime.
Add Docker and Docker Compose support for local development.
Include Django web, Postgres, Qdrant, Neo4j, and only add Redis/worker if needed.
Add .dockerignore and .env.example.
Verify docker compose config.
```

## Testing Strategy

Use three levels of tests:

1. Unit tests with fake ports.
2. Golden tests for Persian legal chunking.
3. Integration tests for Qdrant, Neo4j, LLMs, HuggingFace, and RAGAS.

Normal unit tests should not require live external services.

Mark external tests explicitly, for example:

```text
pytest -m integration
```

## How To Add A New Skill

Add a new skill only when a workflow becomes repeated, complex, or fragile enough to deserve its own guide.

Good candidates:

- `persian-legal-chunking`
- `neo4j-legal-graph-schema`
- `qdrant-retrieval-adapter`
- `ragas-persian-legal-evaluation`
- `django-legal-api`
- `persian-legal-docker-runtime`

Recommended process:

1. Create a new folder under `persian-legal-assistant-codex-skills/`.
2. Add a required `SKILL.md`.
3. Add optional `references/` files for detailed contracts.
4. Add optional `agents/openai.yaml` for UI metadata.
5. Keep the skill concise and action-oriented.
6. Validate that the skill has clear frontmatter: `name` and `description`.

Minimal structure:

```text
persian-legal-assistant-codex-skills/my-new-skill/
  SKILL.md
  references/
  agents/openai.yaml
```

Minimal `SKILL.md`:

```markdown
---
name: my-new-skill
description: Explain what this skill does and exactly when Codex should use it.
---

# My New Skill

## Overview

Explain the job this skill performs.

## Workflow

1. Inspect the existing code.
2. Follow the project architecture rules.
3. Implement the smallest useful change.
4. Add tests.
```

## How To Update An Existing Skill

When updating a skill:

1. Edit the relevant `SKILL.md` only if the core workflow changes.
2. Put detailed schemas, examples, and contracts in `references/`.
3. Keep vendor-specific details inside phase-specific skills, not the shared architecture skill.
4. Avoid duplicating the same rule across many skills; put shared rules in `persian-legal-architecture`.
5. After editing, ask Codex to run a quick structural validation.

Suggested prompt:

```text
Review and update $persian-legal-graphrag-ingestion.
Add guidance for [specific new workflow].
Keep SKILL.md concise and put detailed examples in references/.
Validate the skill structure after editing.
```

## Installing Skills Globally

The skills currently live inside this repository. That is useful for project-local development.

If you want Codex to discover them globally in future threads, copy each skill folder into:

```text
~/.codex/skills/
```

Example:

```bash
cp -R persian-legal-assistant-codex-skills/persian-legal-architecture ~/.codex/skills/
```

Repeat for the other skill folders.

Project-local copies should remain in this repository so the implementation instructions stay versioned with the code.

## Git Notes

Do not commit:

- secrets;
- API keys;
- database passwords;
- generated model weights;
- large downloaded datasets;
- local `.DS_Store` files;
- virtual environments.

Commit:

- source code;
- tests;
- configuration templates;
- small golden test fixtures;
- project-local skills;
- documentation.
