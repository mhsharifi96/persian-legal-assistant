# Persian Legal Assistant

This repository is the main implementation workspace for a PhD thesis project:

**Design and evaluation of an intelligent Persian legal question-answering assistant based on large language models.**

The project target is a modular Persian LegalTech system for Iranian law. It will combine legal document ingestion, Agentic RAG, citation-grounded Persian answers, lawyer recommendation, and automated evaluation for hallucination and retrieval quality.

## Repository Status

This repository currently contains project instructions and local Codex skills. The implementation should start from the architecture and Phase 1 ingestion foundation.

Important files and folders:

```text
AGENT.md
persian-legal-assistant-codex-skills/
```

- `AGENT.md`: project-level instructions for Codex and future agents.
- `persian-legal-assistant-codex-skills/`: local project skills that explain how to implement each phase.

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
