# UI Contracts

Concrete contracts for the Next.js frontend. The frontend is an HTTP client of the DRF API in `$persian-legal-admin-api`; its `references/admin-api-contracts.md` endpoint table is the source of truth. This file pins the client shape, types, page contracts, RTL/citation rules, and the "no mock data" workflow.

## 1. Typed API client

One wrapper owns base URL, auth, headers, and error mapping. Components never call `fetch` directly.

```ts
// lib/api/client.ts
const BASE = process.env.API_BASE_URL!; // server-side; proxy for the browser

export class ApiError extends Error {
  constructor(public status: number, public detail: string) { super(detail); }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json() as Promise<T>;
}
```

Per-resource modules mirror the endpoint table:

```ts
// lib/api/lawyers.ts
export const listLawyers = (q: LawyerQuery) => apiFetch<Lawyer[]>(`/api/lawyers?${qs(q)}`);
export const recommendLawyers = (body: RecommendRequest) =>
  apiFetch<Recommendation[]>(`/api/lawyers/recommend`, { method: "POST", body: JSON.stringify(body) });
// lib/api/ask.ts
export const ask = (body: AskRequest) =>
  apiFetch<AskResponse>(`/api/ask`, { method: "POST", body: JSON.stringify(body) });
```

Endpoints consumed (all under `/api/`, per admin-api skill):

| UI feature            | Endpoint                       | Client fn |
|-----------------------|--------------------------------|-----------|
| Lawyer list/CRUD      | `GET/POST /lawyers`            | `listLawyers`, `upsertLawyer` |
| Recommendation        | `POST /lawyers/recommend`     | `recommendLawyers` |
| Documents / chunks    | `GET /documents`, `/chunks`   | `listDocuments`, `listChunks` |
| Evaluations           | `GET/POST /evaluations`       | `listEvaluations`, `createEvaluation` |
| Run evaluation        | `POST /evaluations/run`       | `runEvaluation` |
| Ask (Q&A)             | `POST /ask`                   | `ask` |

## 2. Types mirror DRF domain DTOs

Types reflect what the serializers return (domain DTOs, not ORM). Keep hierarchy metadata and citations intact.

```ts
export interface Lawyer {
  id: string; name: string; specialties: string[]; location: string;
  success_rate: number;
}
export interface Recommendation { lawyer: Lawyer; score: number; rationale_fa: string; }

export interface Chunk {
  chunk_id: string; document_id: string; law_title: string; jurisdiction: string;
  document_type: string; book?: string; bab?: string; fasl?: string;
  article_number?: string; note_number?: string; effective_date?: string;
  publication_date?: string; version?: string; text: string;
}

export interface Citation { chunk_id: string; document_id: string; label_fa: string; }
export interface AskResponse {
  answer_fa: string;
  citations: Citation[];
  insufficient_context: boolean;
  warning_fa?: string;      // e.g. jurisdiction/staleness warning
}

export interface EvaluationMetrics {
  context_precision: number; faithfulness: number;
  answer_relevancy: number; citation_grounding: number;
}
```

Inspect real responses before finalizing field names; match the backend exactly.

## 3. Page contracts

- **`/lawyers`** — filterable list (specialty, location) + recommendation form. Render `Recommendation[]` sorted by `score`, always showing `rationale_fa`. No client-side scoring; the API owns the score.
- **`/documents`** — list documents; drill into chunks showing hierarchy (کتاب/باب/فصل/ماده/تبصره), dates, and version read-only.
- **`/evaluations`** — table of records + a metrics dashboard from `EvaluationMetrics`. Use `$dataviz` before building charts; theme-aware, RTL axes/legends.
- **`/ask`** — chat form → `POST /ask`. Render `answer_fa`, a citations list where each `Citation` links to its `document_id`/`chunk_id`, and `warning_fa` when `insufficient_context` is true. Loading and error states are Persian. Never synthesize an answer or citation client-side.

## 4. RTL, Persian, and citations

- Root layout: `<html lang="fa" dir="rtl">`, self-hosted Persian font (Vazirmatn), Tailwind logical utilities (`ps-`/`pe-`/`ms-`/`me-`) so mirroring is automatic.
- Display Persian/Arabic text and digits **unnormalized**. Only normalize for keys/matching in code, never for what the user sees.
- Citation components render the API-provided `chunk_id`/`document_id`; they must not fabricate or reformat legal identifiers into something that no longer maps back to a real chunk.

## 5. Auth

- Prefer login via a Next Route Handler that sets an httpOnly cookie; server components/handlers attach the token to API calls. Avoid `localStorage` tokens.
- Never place a secret in `NEXT_PUBLIC_*`. Only non-secret config (e.g. a public API URL for browser calls, or route through a Next proxy) is client-exposed.
- Authenticated/write pages show a Persian sign-in prompt when unauthenticated — no fake session.

## 6. SEO & metadata

Public legal content must be crawlable; private surfaces must not be indexed. Drive metadata from real API data.

```ts
// app/documents/[id]/page.tsx
export async function generateMetadata(
  { params }: { params: { id: string } },
): Promise<Metadata> {
  const doc = await getDocument(params.id);           // real API data
  return {
    title: `${doc.law_title} — ماده ${doc.article_number ?? ""}`.trim(),
    description: doc.text.slice(0, 160),
    alternates: { canonical: `/documents/${doc.document_id}` },
    openGraph: { locale: "fa_IR", title: doc.law_title, type: "article" },
  };
}
// app/evaluations/page.tsx  (authenticated)
export const metadata: Metadata = { robots: { index: false, follow: false } };
```

- `app/layout.tsx` sets `metadataBase` and the default `openGraph.locale = "fa_IR"`; keep `<html lang="fa" dir="rtl">`.
- `app/sitemap.ts` lists only real, public records (published documents, public lawyer profiles); `app/robots.ts` disallows `/evaluations`, admin, auth, and proxy/Route Handler paths.
- Per-user `ask` result views set `robots.index = false` — model-generated answers are not indexable pages.
- JSON-LD (`Person`/`LegalService`, `Legislation`/`Article`, `BreadcrumbList`) only where it mirrors what the page shows; no `FAQPage`/`QAPage` markup on generated answers.
- One `<h1>` per page; Persian `alt`/link text; preload the self-hosted Persian font with `font-display: swap` to protect LCP/CLS.

## 7. "No mock data" workflow

- Runtime pages fetch from the real API only. There is no hard-coded lawyer/document/answer/metric on a page and no fake fallback when a request fails.
- Mocks and fixtures live under the test setup (and optionally Storybook), imported only by tests/stories — never by `app/**` runtime code.
- Derive test fixtures from real serializer output so contract drift is caught.

## Acceptance recap

- HTTP-only client; typed responses; no Python/ORM/DB/vendor-SDK access from the frontend.
- RTL + Persian font; legal text and citations rendered unnormalized.
- Four surfaces wired to the correct endpoints with matching types.
- Citations link real `chunk_id`/`document_id`; insufficiency/jurisdiction warnings shown when present.
- No mock data or fake fallback on runtime pages; secrets stay server-side; config is env-driven.
