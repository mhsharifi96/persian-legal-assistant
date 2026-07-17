---
name: persian-legal-lawyer-fetcher
description: Fetch public Iranian lawyer-directory records from search-hamivakil.ir, normalize them to the Persian Legal Assistant lawyer JSONL schema, resume interrupted province/bar runs, and import the result through Django. Use when collecting or refreshing real lawyer profiles by bar association, investigating source-schema changes, or preparing lawyer datasets for `manage.py import_lawyers`.
---

# Persian Legal Lawyer Fetcher

Fetch public professional-directory records conservatively and convert them to
the project's canonical lawyer import format. Keep fetching separate from the
Django database: produce reviewable JSONL first, then use the existing
idempotent import command.

## Required workflow

1. Confirm the requested collection is permitted by the source's current terms,
   robots policy, and applicable privacy rules. Stop if authorization is unclear.
2. Read `references/source-contract.md` when changing mappings, diagnosing source
   responses, or handling a schema change.
3. Run one bar first and inspect the JSONL before expanding the scope.
4. Keep the default delay and sequential requests. Treat HTTP 403/429 as a stop
   signal; do not rotate user agents, IPs, cookies, or identities to evade it.
5. Review records for accuracy and data minimization before importing.
6. Import through `manage.py import_lawyers`; do not write directly to ORM tables.

## Fetch one bar

Run from the repository root:

```bash
python3 persian-legal-assistant-codex-skills/persian-legal-lawyer-fetcher/scripts/fetch_lawyers.py \
  --bar "آذربایجان شرقی" \
  --output data/import/lawyers.jsonl
```

The script accepts either the displayed Persian bar name or its source ID. It
creates a checkpoint beside the output and skips source IDs already present, so
the same command is safe to resume.

After bounded retries, an empty HTTP body is logged in the final `empty_bars`
summary and the run continues. That bar is intentionally not checkpointed as
complete, so rerunning the same command retries it.

## Fetch several or all bars

Prefer an explicit, bounded list:

```bash
python3 persian-legal-assistant-codex-skills/persian-legal-lawyer-fetcher/scripts/fetch_lawyers.py \
  --bar "آذربایجان شرقی" \
  --bar "اردبیل" \
  --output data/import/lawyers.jsonl
```

Use `--all-bars` only after the single-bar output is verified. The script runs
sequentially, waits between bars, and flags any response of exactly 300 records
as potentially truncated by the source.

## Normalize a saved response

Use offline replay for parser work without calling the source:

```bash
python3 persian-legal-assistant-codex-skills/persian-legal-lawyer-fetcher/scripts/fetch_lawyers.py \
  --input-json /path/to/response.json \
  --bar "آذربایجان شرقی" \
  --output /tmp/lawyers.jsonl
```

## Fetch a Dadrah request-ID range

Only run this collection after confirming that Dadrah permits the intended bulk
use. The range fetcher uses ten worker threads by default, but a shared limiter
spaces request starts across all threads. HTTP 401, 403, or 429 stops the run.

The defaults cover request IDs `800000` through `891818` inclusively and create
ten JSONL files plus ten checkpoint files:

```bash
python3 persian-legal-assistant-codex-skills/persian-legal-lawyer-fetcher/scripts/fetch_dadrah.py \
  --start-id 800000 \
  --end-id 891818 \
  --chunks 10 \
  --workers 10 \
  --output-directory data/import/dadrah
```

The same command safely resumes from each chunk checkpoint. Each JSONL line
represents one request page with one `question` object and an `answers` array;
each answer contains its associated `lawyer` object. Missing pages and exhausted
request errors are also recorded for review. Keep the default global delay
unless the source explicitly permits a different rate. Do not resume into files
written by the older `records` schema; choose a new output directory first.

## Import into Django

```bash
docker compose exec web python manage.py import_lawyers /path/inside/container/lawyers.jsonl
```

If the output is on the host and not mounted in the container, copy it to a
temporary container path or run the management command in a host environment
configured for the same database.

## Safety and data-quality rules

- Collect only fields needed for the professional directory use case. The
  bundled script discards mobile numbers and does not query national IDs.
- Preserve source attribution, source record ID, bar, professional state,
  degree, and public office address in `metadata`.
- Leave `specialties` empty and `success_rate` at `0.0` when the source does not
  provide those facts. Never infer or fabricate them.
- Never commit cookies, raw responses containing contact data, API keys, or the
  generated dataset.
- On repeated errors, save progress and report the failing bar and status. Do
  not bypass CAPTCHA, access controls, rate limits, or blocking.
- Continue after an exhausted empty-body response, but do not treat malformed
  JSON, HTML access pages, or HTTP 401/403/429 as an empty result.
- On the first HTML response, clear the stale cookie jar and retry once with a
  freshly bootstrapped session. Stop if HTML is returned again; do not change
  user agent, proxy, IP address, or identity.
- If the source schema differs from `references/source-contract.md`, stop and
  update the mapping with a small saved fixture before resuming network fetches.

## Resources

- `scripts/fetch_lawyers.py`: deterministic fetch, normalization, deduplication,
  checkpoint, and JSONL writer.
- `references/bars.json`: source bar/province display names and IDs.
- `references/source-contract.md`: observed request/response contract and field
  mapping.
