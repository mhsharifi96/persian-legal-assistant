---
name: persian-legal-graphrag-ingestion
description: Implement Phase 1 of a Persian legal assistant: document ingestion, Persian/Iranian legal hierarchy parsing, hierarchical chunking, embeddings, Qdrant vector storage, LLM-based knowledge graph extraction, Neo4j ingestion, and hybrid GraphRAG retrieval. Use when building or modifying ingestion pipelines for Iranian legal PDFs, legal codes, articles, notes, citations, GraphRAG, Qdrant, Neo4j, LlamaParse, LangChain, or Persian embedding models.
---

# Persian Legal GraphRAG Ingestion

## Overview

Implement the data foundation for the thesis system: parse Iranian legal documents, preserve legal hierarchy in chunk metadata, index dense vectors, extract graph entities and relations, and expose a hybrid retriever. Keep all provider choices behind ports so parser, embedding model, vector store, graph store, or LLM can be replaced.

## Use Architecture Skill

If the repository does not already enforce ports and adapters, also use `$persian-legal-architecture` before implementing this phase.

## Workflow

1. Inspect existing project layout, settings, tests, and any current RAG code.
2. Define or reuse ports for parsing, chunking, embeddings, vector store, graph store, LLM, and hybrid retrieval.
3. Implement document parsing through `DocumentParserPort`; default adapter: LlamaParse for complex Iranian legal PDFs.
4. Implement Persian legal hierarchical chunking for `کتاب`, `باب`, `فصل`, `ماده`, and `تبصره`.
5. Add embedding adapter; default model: `MCINext/Hakim-small`.
6. Add vector repository; default adapter: Qdrant.
7. Add graph extraction service using structured LLM JSON output.
8. Add graph repository; default adapter: Neo4j.
9. Implement `HybridRetriever` using vector search plus graph expansion.
10. Add unit tests with fake repositories and focused golden tests for Persian legal chunking.

Read `references/ingestion-contracts.md` before writing code.

## Non-Negotiable Metadata

Every chunk must carry lineage metadata:

```text
document_id, source_uri, jurisdiction, law_title, document_type,
book, bab, fasl, article_number, note_number,
effective_date, publication_date, version, page_start, page_end,
char_start, char_end, parser_name, chunking_strategy
```

Do not store only raw text and vector. The hierarchy prevents the legal boundary problem where an answer cites an article without its governing book, chapter, article, or note context.

## Graph Schema

Use conservative graph types first:

- Entity labels: `Law`, `Article`, `Note`, `Concept`, `Penalty`, `Court`, `PersonRole`, `Organization`, `Procedure`, `Deadline`.
- Relation types: `CONTAINS`, `REFERENCES`, `AMENDS`, `REPEALS`, `DEFINES`, `IMPOSES`, `APPLIES_TO`, `EXCEPTION_TO`, `HAS_DEADLINE`.

Keep labels and relation names configurable.

## Acceptance Checks

- A sample law text containing `ماده` and multiple `تبصره` entries produces separate chunks with correct lineage.
- The embedding model can be replaced by changing settings and adapter wiring.
- Qdrant and Neo4j SDK calls do not appear in application services.
- Graph extraction validates JSON schema and handles malformed LLM output gracefully.
- `HybridRetriever.retrieve()` returns contexts with text, vector score, hierarchy, citations, and graph neighbors.
