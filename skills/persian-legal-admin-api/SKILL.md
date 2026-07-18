---
name: persian-legal-admin-api
description: Build the Persian Legal Assistant admin UI and HTTP API on Django + Django REST Framework over real persisted data (no fake/in-memory adapters). Use when adding or reviewing Django settings, ORM persistence adapters, migrations, Django admin registration, DRF serializers/viewsets/routers, authentication and permissions, management commands that seed real Iranian legal data and lawyers, or API endpoints that expose lawyer recommendation, document/chunk management, evaluation records, and the agentic Persian Q&A flow.
---

# Persian Legal Admin & API

## Overview

Use this skill to add a Django admin UI and a Django REST Framework API that operate on **real, persisted data** — real Iranian legal documents/chunks, real lawyer profiles, and real evaluation records — not the fake in-memory adapters used by unit tests. The admin and API are the `interfaces/` layer; they must call application services and go through ports, never vendor SDKs or business logic reimplemented in a view.

The stack is fixed: **Django** (admin UI + settings + ORM persistence), **Django REST Framework** (JSON API). This resolves the "API framework style" open decision in `memory.md` in favor of Django + DRF, matching `project_structure.md` (`manage.py`, `config/settings/`, DRF serializers) and the Docker plan in `AGENT.md`.

## Prerequisites

Read before implementing:

1. `AGENT.md` — architecture rules and dependency direction.
2. `memory.md` — current phase status; the ORM/admin/API layer is new work on top of Phases 1–3.
3. `project_structure.md` — expected `interfaces/`, `config/`, and Django layout.
4. `$persian-legal-architecture` — ports/adapters, provider registry, and configuration rules. **Apply it first** because this skill introduces a new external dependency (the database) behind existing ports.
5. `references/admin-api-contracts.md` — concrete model↔domain mapping, repository write ports, serializer/viewset contracts, and the "no fake data" seeding workflow.

Inspect existing code before adding files: `application/ports.py`, `application/services/`, `application/agentic/`, `application/evaluation/`, `domain/models.py`, `config/settings.py`, `config/bootstrap.py`, and `infrastructure/repositories/`.

## Core Rule — Real Data, No Fakes in the Delivered App

- The admin and the API must read and write a **real database** (Postgres in Docker; SQLite acceptable only for local scratch). The `fake`/`memory` adapters remain for unit tests only.
- Do **not** ship fabricated lawyers, documents, or evaluation rows as application seed data. Populate real data through migrations + management commands that import from a real source file/dataset the user provides, or through the admin/API itself. Test fixtures stay under `tests/`.
- Provider selection stays env-driven. Add real ORM-backed adapters to the existing provider registries and switch to them by configuration, e.g. `LAWYER_REPO_PROVIDER=orm`, never by editing service code.
- If no real dataset exists yet, ship **empty** tables plus a documented import command and admin entry — an empty real store, not a fake-populated one.

## Dependency Direction (do not violate)

```text
interfaces/api (DRF), interfaces/admin (Django admin) -> application services/ports -> domain
infrastructure/repositories/orm (Django ORM adapters) -> application ports -> domain
config (Django settings + bootstrap) -> infrastructure + application
```

- `domain/` and `application/` must not import `django.*`, DRF, or ORM models. Keep the existing `dataclass`/`Protocol` domain and ports untouched by Django.
- Django ORM models live in `infrastructure/` (or a Django app under `interfaces/`) and are a **persistence detail**, separate from `domain/models.py`. Adapters map ORM rows ↔ domain objects (`LawyerProfile`, `LegalDocument`, `LegalChunk`, `EvaluationRecord`).
- DRF viewsets for business operations (recommend a lawyer, answer a question, run evaluation) call the corresponding **application service**, not the ORM or vendor SDKs.

## Package Shape

Prefer this layout; keep local names if the repo already differs but preserve boundaries:

```text
src/legal_assistant/
  infrastructure/
    repositories/
      orm/
        models.py        # Django ORM models (persistence only)
        lawyers.py        # OrmLawyerRepository  (domain <-> ORM)
        documents.py      # OrmDocumentRepository / chunk store
        evaluation.py     # OrmEvaluationRepository
  interfaces/
    api/
      serializers.py      # DRF serializers over domain DTOs
      views.py            # DRF viewsets/APIViews -> application services
      urls.py             # DRF router registration
      permissions.py
    admin/
      apps.py
      admin.py            # Django admin registration over ORM models
    management/
      commands/
        import_lawyers.py         # real-data import (no fabricated rows)
        import_legal_documents.py
config/
  settings/
    base.py               # Django settings; reads env, builds legal_assistant Settings
    local.py
    test.py
  urls.py                 # includes interfaces/api/urls
  asgi.py
  wsgi.py
manage.py
```

## Required Work

### 1. Persistence adapters (real repositories)

- Add Django ORM models for `LawyerProfile`, `LegalDocument`, `LegalChunk` (preserving the full Iranian legal hierarchy metadata: `document_id, source_uri, jurisdiction, law_title, document_type, book, bab, fasl, article_number, note_number, effective_date, publication_date, version, page_start, page_end, char_start, char_end, parser_name, chunking_strategy`), and `EvaluationRecord`.
- Implement `OrmLawyerRepository` satisfying the existing read `LawyerRepository` port, plus `OrmEvaluationRepository` for `EvaluationRepository`.
- Admin/API writes need write capability the current read-only ports lack. Add **narrow write ports** (e.g. `LawyerWriteRepository`, `DocumentStore`) in `application/ports.py` rather than widening read ports or writing ORM directly from a service. See `references/admin-api-contracts.md`.
- Register each ORM adapter in the matching `*_BUILDERS` registry in `config/bootstrap.py` and select via settings (`LAWYER_REPO_PROVIDER=orm`, etc.). Keep `fake`/`memory` builders for tests.

### 2. Django admin (the admin UI)

- Register ORM models with `ModelAdmin` classes: list displays, search, and filters keyed on real legal fields (`law_title`, `jurisdiction`, `document_type`, `article_number`, lawyer specialties/location, evaluation metadata).
- Django admin operates directly on ORM models — this is the one sanctioned place that touches persistence directly, because admin is a data-management tool over the persistence adapter, not business logic. Do **not** put recommendation/answer/evaluation *logic* in admin actions; if an admin action must trigger such logic, call the application service.
- Ensure Persian text renders correctly (UTF-8, right-to-left where the template allows); do not normalize away original Persian/Arabic characters for display.

### 3. DRF API

Expose all four surfaces:

- **Lawyers**: CRUD viewset. Reads go through `LawyerRepository`; writes through the write port. Recommendation endpoint (`POST /api/lawyers/recommend`) calls `LawyerRecommendationService` and returns scored results with the Persian rationale.
- **Legal documents/chunks**: browse/manage ingested output; expose hierarchy metadata read-only where it is derived by ingestion.
- **Evaluation records**: list/create `EvaluationRecord`s; an endpoint to run `EvaluationService` over stored records and return RAGAS-style metrics.
- **Q&A / ask**: `POST /api/ask` runs the agentic graph (`build_agentic_graph`) and returns the formal Persian answer with structured `chunk_id` citations and any insufficiency warning. This endpoint requires a real `LLMPort`/retriever wiring — if a real LLM provider is not yet configured, return a clear, typed error, do not silently fall back to fakes in a production profile.

Serializers must serialize the **domain DTOs** returned by services (not ORM models) for business endpoints, so the API contract is stable across persistence changes.

### 4. Auth, config, and safety

- Add authentication (DRF token/session) and permission classes; admin and write endpoints must not be anonymous.
- Reconcile Django settings with `legal_assistant`'s typed `Settings`: `config/settings/base.py` reads env and constructs `Settings.from_env()`, and the bootstrap builders provide adapters. Do not duplicate provider selection logic in two places.
- Never hard-code `SECRET_KEY`, database URLs, API keys, model names, or collection/label names. Use env + `.env.example`. Do not commit `.env`, DB volumes, or migrations containing data.

## Testing Expectations

- Unit-test ORM adapters against the port contracts using Django's test DB (or SQLite), asserting domain↔ORM mapping round-trips and hierarchy-metadata preservation.
- API tests: use DRF `APITestCase`; assert business endpoints call services (fakes acceptable *in tests only*), auth is enforced, and Persian text + citations survive serialization.
- Keep live-service tests (real LLM, Qdrant, Neo4j) behind integration markers.
- Run `pyrefly check`; type all view/serializer/adapter inputs and outputs.

## Acceptance Checks

- The delivered admin and API operate on a real database; switching `LAWYER_REPO_PROVIDER=fake→orm` (and peers) changes only configuration.
- No fabricated lawyers/documents/evaluation rows are seeded by application code; real data enters via migrations + import commands or the admin/API.
- `domain/` and `application/` contain zero `django`/DRF/ORM imports; ORM models live in infrastructure/interfaces.
- Business endpoints (recommend, ask, evaluate) route through application services; only Django admin and CRUD persistence touch ORM directly.
- Iranian legal hierarchy metadata and Persian citations are preserved end-to-end from DB → service → serializer → JSON.
- Auth is enforced on admin and all write/business endpoints; no secrets or provider names are hard-coded.
