# Project Memory

Use this file for current decisions and status. Historical implementation
details belong in `CHANGELOG.md` and Git history.

## Current Status

- Repository: `persian-legal-assistant`
- Main branch: `main`
- The repository was reduced on 2026-07-20, then a focused legal research
  application and Deep Agents adapter were reintroduced on 2026-07-21.
- PDF ingestion is implemented through `DocumentIngestionService`, with Django
  persistence, PyPDF extraction, hashing/OpenAI embeddings, and Qdrant storage.
- Standalone Neo4j importers cover Dadrah consultations, Dadrah lawyer profiles,
  and NovinLaw crawler databases.
- Local datasets, crawler state, SQLite databases, caches, secrets, and generated
  output are not source code and must remain untracked.
- The current agent uses Qdrant semantic search and parameterized, allowlisted
  Neo4j expansion through provider-neutral ports. It loads four packaged legal
  skills, has a bounded tool budget, and validates cited source IDs after model
  generation.
- The previous evaluation, recommendation, web API, and frontend remain removed.
  Git history is the reference if any of them are intentionally restored.
- The unit suite covers application validation, retrieval adapters, agent
  grounding/insufficient-context behavior, settings, and current Deep Agents
  construction without live external services.

## Architecture Decisions

- Keep domain/application contracts independent of Django and provider SDKs.
- Keep OpenAI, Qdrant, Neo4j, and parser SDK usage in infrastructure adapters.
- Select providers, models, URLs, collection names, and credentials through
  configuration rather than hard-coding them.
- Preserve Persian legal text and citations; normalize characters or digits only
  for matching and stable identifiers.
- Keep Deep Agents in an infrastructure adapter. Its built-in write, delete,
  shell, broad filesystem, and subagent tools are disabled for the legal runtime.

## Next Priorities

- Add integration tests against disposable Qdrant and Neo4j containers.
- Add an authenticated/rate-limited HTTP interface over `LegalAgentService`.
- Add evaluation records for retrieval quality, citation grounding, and Persian
  legal-answer faithfulness.
- Add unit tests for text splitting, ingestion failure handling, manifest joins,
  and crawler parsing.
- Add static linting for unused imports and dead code.
- Reintroduce broader application features only when their product scope is
  explicitly defined.
