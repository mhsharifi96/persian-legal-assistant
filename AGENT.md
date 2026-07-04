# AGENT.md

## Project

This repository is the main implementation workspace for the Persian Legal Assistant thesis project:

Design and evaluation of an intelligent Persian legal question-answering assistant based on large language models.

The system should support Iranian legal document ingestion, Agentic RAG, citation-grounded Persian answers, lawyer recommendation, and evaluation against hallucination and retrieval quality.

## Use Local Codex Skills

Before implementing major features, inspect the local skill package:

```text
persian-legal-assistant-codex-skills/
```

Use these skills as project-specific instructions:

- `$persian-legal-architecture`: repository, port, adapter, dependency injection, configuration, and testing architecture.
- `$persian-legal-graphrag-ingestion`: Phase 1, legal document parsing, hierarchical chunking, embeddings, Qdrant, Neo4j, and HybridRetriever.
- `$persian-legal-agentic-core`: Phase 2, LangGraph reasoning core, query decomposition, retrieval, judge loop, and Persian answer generation.
- `$persian-legal-evaluation-recommender`: Phase 3, lawyer recommendation and RAGAS-style evaluation.

If a task touches external services or replaceable providers, apply `$persian-legal-architecture` first.

## Architecture Rules

Keep the core code independent from vendors and infrastructure.

- Domain and application layers must not import Qdrant, Neo4j, OpenAI, HuggingFace, LlamaParse, LangGraph, CrewAI, RAGAS, Django, or Pandas directly unless the existing architecture explicitly places them there.
- Put external SDK usage in infrastructure adapters.
- Define stable ports in the application layer.
- Wire concrete implementations through settings/bootstrap.
- Make provider names, model names, database URLs, collection names, graph labels, and scoring weights configurable.

Preferred package direction:

```text
interfaces -> application -> domain
infrastructure -> application -> domain
config/bootstrap -> infrastructure + application
```

## Replaceability Requirement

Changing any of these must not require rewriting core use cases:

- embedding model, including replacing `MCINext/Hakim-small`;
- vector database, including replacing Qdrant;
- graph database, including replacing Neo4j;
- LLM provider or model;
- parser provider, including replacing LlamaParse;
- evaluation backend or judge LLM;
- lawyer data repository.

## Implementation Phases

### Phase 1: GraphRAG Ingestion

Implement ingestion around these boundaries:

- `DocumentParserPort`
- `LegalChunkerPort`
- `EmbeddingModelPort`
- `VectorStoreRepository`
- `GraphRepository`
- `LLMPort`
- `HybridRetrieverPort`

Every legal chunk must preserve structural metadata for Iranian law:

```text
document_id, source_uri, jurisdiction, law_title, document_type,
book, bab, fasl, article_number, note_number,
effective_date, publication_date, version, page_start, page_end,
char_start, char_end, parser_name, chunking_strategy
```

Chunking must recognize at least:

```text
کتاب، باب، فصل، ماده، تبصره
```

### Phase 2: Agentic Core

Implement the reasoning flow with a typed state and bounded self-reflection:

```text
router -> query_decomposition -> retrieval -> judge
judge valid -> generation -> end
judge invalid and retry_count < max -> retrieval/decomposition
judge invalid and retry_count >= max -> limited answer with warning
```

Generated answers must be formal Persian, cite retrieved legal sources, and clearly state limitations when context is insufficient.

### Phase 3: Recommendation and Evaluation

Implement lawyer recommendation as an application service over:

- `LawyerRepository`
- `EmbeddingModelPort`
- configurable scoring weights

Start with a transparent weighted score:

```text
final_score = semantic_weight * cosine_similarity + success_weight * normalized_success_rate + location_weight * location_match
```

Implement evaluation with records containing:

```text
question, answer, contexts, ground_truth, citations, metadata
```

Use RAGAS-style metrics for context precision, faithfulness, answer relevancy, and legal/citation grounding.

## Testing Expectations

- Add unit tests for application services using fake ports.
- Add golden tests for Persian legal chunking.
- Keep external service tests behind integration markers.
- Do not require live Qdrant, Neo4j, OpenAI, or HuggingFace access for normal unit tests.
- Test insufficient-context behavior and citation preservation in the agentic core.

## Coding Guidance

- Prefer small, typed, testable services.
- Keep Persian legal terms and citations intact.
- Normalize Persian/Arabic digits only for IDs and matching; preserve original text for display and citations.
- Avoid broad refactors unless required by the task.
- Do not commit secrets, API keys, database passwords, or generated model artifacts.

