---
name: persian-legal-nextjs-ui
description: Build the Persian Legal Assistant web frontend as a Next.js (App Router, TypeScript) application that consumes the Django REST Framework API over HTTP against real data. Use when adding or reviewing the Next.js app, RTL/Persian layout and fonts, a typed API client for the DRF endpoints, pages for lawyer search/recommendation, legal document/chunk browsing, evaluation dashboards, and the agentic Persian Q&A chat with citations, plus auth token handling, environment configuration, and the web-ui Docker service.
---

# Persian Legal Next.js UI

## Overview

Use this skill to build the user-facing web frontend as a **Next.js App Router + TypeScript** application. The frontend is a pure HTTP client of the Django REST Framework API defined by `$persian-legal-admin-api`: it renders real lawyers, real legal documents/chunks, real evaluation records, and real agentic Persian answers. It must never touch the database, the Python domain/application code, ORM models, or any vendor SDK (Qdrant, Neo4j, OpenAI, HuggingFace) directly — it only calls the API over the network.

The system serves Iranian law in Persian, so the UI is **RTL and Persian-first** by default.

## Stack (fixed defaults)

- **Next.js** with the **App Router** and **React Server Components** where data is fetched.
- **TypeScript**, strict mode. All API responses are typed.
- **Tailwind CSS** for styling with logical properties (RTL-safe).
- A single **typed fetch API client**; no direct `fetch` scattered through components, no GraphQL, no vendor SDKs.

If the repo already has a different but working frontend convention, keep it but preserve these boundaries: HTTP-only, typed client, RTL/Persian, real data.

## Prerequisites

Read before implementing:

1. `AGENT.md` — architecture rules and dependency direction.
2. `$persian-legal-admin-api` — the API this frontend consumes; its `references/admin-api-contracts.md` endpoint table is the contract.
3. `$persian-legal-docker-runtime` — to add the frontend as a Docker Compose service.
4. `references/ui-contracts.md` in this skill — API client shape, page contracts, RTL/citation rules, and the "no mock data" workflow.

Inspect the actual API responses (or the DRF serializers) before hand-writing types, so the frontend types match what the backend returns.

## Core Rule — Real Data, No Mocks in the Delivered App

- The delivered UI renders data returned by the **real API**. Do not ship hard-coded lawyers, documents, answers, or metrics as component data.
- Mock/fixture data exists only in tests and (optionally) Storybook — never on a runtime page or as a fallback that silently replaces a failed API call.
- If the API is unreachable or returns an error, render a clear error/empty state in Persian; do not substitute fabricated content.
- The API base URL and auth come from environment configuration, never hard-coded hosts or tokens.

## Boundary Rules (do not violate)

```text
Next.js app  ->  HTTP  ->  DRF API (interfaces/api)  ->  application services  ->  domain
```

- The frontend depends on the API contract only. A change of embedding model, vector DB, graph DB, or LLM provider must be invisible to the UI as long as the API response shape is stable.
- No database drivers, no Python imports, no ORM, no direct calls to Qdrant/Neo4j/OpenAI from the browser or Next.js server.
- Server-side secrets (session cookies, server-to-API tokens) stay in Route Handlers / Server Components and are never exposed to client bundles (no secret in `NEXT_PUBLIC_*`).

## Package Shape

Keep the frontend in its own top-level directory, separate from the Python `src/legal_assistant` package:

```text
web/                          # or frontend/ — the Next.js app root
  app/
    layout.tsx                # <html lang="fa" dir="rtl">, Persian font, RTL
    page.tsx                  # home / entry
    lawyers/                  # search + recommendation UI
    documents/                # legal document & chunk browsing
    evaluations/             # evaluation records + metrics dashboard
    ask/                      # agentic Persian Q&A chat
    api/                      # optional Next Route Handlers (BFF/proxy, auth)
  lib/
    api/
      client.ts               # typed fetch wrapper (base URL, auth, errors)
      lawyers.ts              # per-resource functions -> API endpoints
      documents.ts
      evaluations.ts
      ask.ts
    types.ts                  # types mirroring DRF serializer output
  components/                 # presentational components (citations, cards)
  styles/                     # Tailwind + RTL/Persian styles
  .env.example                # API_BASE_URL etc. (no secrets committed)
```

## Required Work

### 1. RTL & Persian foundation

- Root `layout.tsx`: `<html lang="fa" dir="rtl">`; load a Persian webfont (e.g. Vazirmatn) self-hosted, not from a normalization-lossy CDN.
- Use CSS logical properties / Tailwind logical utilities so layout mirrors correctly in RTL.
- Preserve original Persian/Arabic characters and digits in display; do **not** normalize legal text or citations for rendering (normalization is only for IDs/matching, per `AGENT.md`).

### 2. Typed API client

- One `client.ts` that reads the API base URL from env, attaches auth, sets JSON headers, and maps non-2xx responses to typed errors surfaced as Persian UI states.
- Per-resource modules whose function signatures mirror the endpoint table in `$persian-legal-admin-api`:
  lawyers CRUD + `recommend`, documents/chunks browse, evaluations list/create/`run`, and `ask`.
- Types in `types.ts` mirror the DRF domain-DTO serializers (lawyer profile with score/rationale, chunk with full hierarchy metadata, evaluation metrics, answer with structured `chunk_id` citations and insufficiency warning).

### 3. Pages (the four surfaces)

- **Lawyers**: search/filter list + a recommendation form that calls `POST /lawyers/recommend` and shows scored results with the **Persian rationale**.
- **Documents/chunks**: browse ingested legal documents; show hierarchy metadata (کتاب/باب/فصل/ماده/تبصره, dates, version) read-only.
- **Evaluations**: list evaluation records and render RAGAS-style metrics (context precision, faithfulness, answer relevancy, citation grounding) as a dashboard — see `$dataviz` before building charts.
- **Ask (Q&A chat)**: submit a Persian legal question to `POST /ask`, render the formal Persian answer, the **structured citations** (each linking to its `chunk_id`/document), and any insufficiency/jurisdiction warning. If the API streams, render incrementally; otherwise show a loading state. Never fabricate an answer client-side.

### 4. Auth & configuration

- Implement login against the API's auth (DRF token/session). Prefer httpOnly cookies via Next Route Handlers over storing tokens in `localStorage`.
- Guard write actions and authenticated pages; unauthenticated users get a Persian sign-in prompt, not a fake session.
- `API_BASE_URL` and any server-side token come from env; provide `.env.example`; never commit real `.env`.

### 5. Docker

- Add a `web-ui` (Next.js) service via `$persian-legal-docker-runtime`; it depends on the `web`/API service and reads the API URL from the compose environment. Do not bake secrets or `.env` into the image.

### 6. SEO & metadata

Persian legal content is a search-discovery asset, so public pages must be crawlable and correctly described — but authenticated/admin surfaces must not be indexed.

- **Server-render indexable content.** Public pages (lawyer directory/profiles, legal document/chunk browsing) fetch on the server (RSC / SSR) so crawlers see real content in the HTML, not a client-only shell. Do not hide primary legal text behind client-only fetches.
- **Metadata API, from real data.** Use Next's `Metadata`/`generateMetadata` (never a fake title). Titles/descriptions derive from the real API response — e.g. a lawyer's name/specialty, a document's `law_title` and article. Set `metadataBase`, canonical URLs (`alternates.canonical`), and Open Graph/Twitter tags with Persian text. Localize: `openGraph.locale = "fa_IR"`.
- **Language/direction signals.** Keep `<html lang="fa" dir="rtl">`. If an English or bilingual variant is ever added, wire `alternates.languages` (hreflang) — until then do not emit hreflang for locales that don't exist.
- **`app/sitemap.ts` + `app/robots.ts`.** Generate the sitemap from real, public API records (published documents, public lawyer profiles) — not fabricated URLs. `robots.ts` allows public routes and disallows `/evaluations`, admin, auth, and any Next Route Handler/proxy paths.
- **Do not index private or thin surfaces.** Authenticated pages (evaluations dashboard, admin-adjacent views) and per-request `ask` result pages set `robots: { index: false }`. The agentic Q&A answers are generated per user and must not be exposed as fabricated/duplicative indexable pages.
- **Structured data (JSON-LD), only when truthful.** Where it reflects real data, emit schema.org JSON-LD: `Person`/`LegalService` for lawyer profiles, `Legislation`/`Article` for legal documents, `BreadcrumbList` for hierarchy. Never mark up content the page doesn't actually show, and never attach `FAQPage`/`QAPage` markup to model-generated answers as if they were authoritative facts.
- **Semantics & Core Web Vitals.** One `<h1>` per page, meaningful heading order, descriptive `alt`/link text in Persian. Self-host the Persian font with `font-display: swap` and preload it to protect LCP/CLS.

## Testing Expectations

- Component/unit tests (e.g. Vitest/Jest + Testing Library) may mock the API client — mocks live in tests only.
- Add at least one end-to-end/integration test that runs the UI against the real API (or a contract fixture derived from real serializer output), asserting Persian text and citations render and RTL is applied.
- Type-check with `tsc --noEmit`; lint. All API responses are typed, no `any` on the client boundary.

## Acceptance Checks

- The delivered UI renders only real API data; no hard-coded lawyers/documents/answers/metrics on runtime pages, and no fake fallback on API failure.
- The frontend makes HTTP calls to the DRF API only — zero Python/ORM/DB/vendor-SDK access.
- Layout is RTL with a Persian font; legal text and citations are shown unnormalized.
- The four surfaces (lawyers+recommend, documents/chunks, evaluations, ask) are wired to the correct endpoints with typed responses.
- Citations reference the real `chunk_id`s/documents returned by the API; insufficiency/jurisdiction warnings are shown when present.
- Secrets stay server-side; API base URL and tokens are env-driven; no secret in `NEXT_PUBLIC_*` or the client bundle.
- Public pages are server-rendered with real-data metadata (canonical, OG, `fa_IR`), `sitemap.ts`/`robots.ts` exist, and authenticated/`ask` pages are `noindex`; JSON-LD is present only where it reflects content the page actually shows.
