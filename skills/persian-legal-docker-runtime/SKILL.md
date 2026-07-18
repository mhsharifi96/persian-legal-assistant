---
name: persian-legal-docker-runtime
description: Containerize, run, test, and maintain the Persian Legal Assistant with Docker and Docker Compose. Use when Codex needs to add or update Dockerfile, docker-compose.yml, compose override files, .dockerignore, container entrypoints, environment templates, health checks, local development commands, or service wiring for Django, Postgres, Redis, Qdrant, Neo4j, Celery, and AI/RAG workers.
---

# Persian Legal Docker Runtime

## Overview

Use this skill to make the project runnable under Docker Compose without weakening the architecture rules in `AGENT.md`. Docker should provide repeatable local development, integration testing, and service orchestration for the Persian Legal Assistant.

## Prerequisites

Before changing Docker files:

1. Read `AGENT.md`.
2. Read `$persian-legal-architecture` if code structure or settings are affected.
3. Inspect existing `Dockerfile`, `docker-compose*.yml`, `.dockerignore`, `.env.example`, dependency files, and Django settings.
4. Read `references/docker-compose-contract.md` for service contracts and command conventions.

## Default Compose Stack

Prefer a development stack with these services when they are relevant to the current implementation phase:

- `web`: Django/API service.
- `worker`: optional Celery/RQ/background worker for ingestion and graph extraction.
- `postgres`: relational database.
- `redis`: cache/broker.
- `qdrant`: vector database for Phase 1.
- `neo4j`: graph database for Phase 1.

Do not add services that the current phase does not need. Phase 1 can start with `web`, `postgres`, `qdrant`, and `neo4j`; add `redis` and `worker` when background jobs exist.

## Dockerfile Rules

- Use a slim Python base image unless the project needs GPU or system libraries.
- Install only required OS packages.
- Use a non-root runtime user.
- Keep dependency installation cached by copying dependency files before application code.
- Do not bake secrets or `.env` files into images.
- Prefer explicit commands for `web`, `worker`, `test`, and management tasks.
- Keep production assumptions out of the dev Dockerfile unless the user asks for deployment hardening.

## Compose Rules

- Put secrets in `.env` or Compose environment variables; commit only `.env.example`.
- Use named volumes for database and vector/graph storage.
- Add health checks for stateful services where practical.
- Use `depends_on` with health conditions when supported.
- Expose only ports needed for local development.
- Make service names stable because application settings may reference them.

## Required Developer Commands

When adding Docker support, document and verify these commands if the project has the needed files:

```bash
docker compose up --build
docker compose down
docker compose logs -f web
docker compose exec web python manage.py migrate
docker compose exec web python manage.py test
```

For pytest projects, prefer:

```bash
docker compose exec web pytest
docker compose exec web pytest -m integration
```

## Environment Template

Maintain `.env.example` with safe placeholder values for:

```text
DJANGO_SECRET_KEY
DJANGO_DEBUG
DATABASE_URL
REDIS_URL
QDRANT_URL
NEO4J_URI
NEO4J_USERNAME
NEO4J_PASSWORD
EMBEDDING_PROVIDER
EMBEDDING_MODEL_NAME
LLM_PROVIDER
OPENAI_API_KEY
LEGAL_JURISDICTION
```

Never commit real API keys, passwords, or private model tokens.

## Acceptance Checks

- `docker compose config` succeeds.
- `docker compose up --build` starts the selected stack.
- Django management commands can run inside `web`.
- External services have stable container hostnames matching settings.
- `.dockerignore` prevents copying virtualenvs, caches, secrets, local DBs, model caches, and large datasets into images.
- Docker changes do not hard-code provider choices in application logic.

