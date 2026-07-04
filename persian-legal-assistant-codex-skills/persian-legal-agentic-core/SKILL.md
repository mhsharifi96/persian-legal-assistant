---
name: persian-legal-agentic-core
description: Implement Phase 2 of a Persian legal assistant: LangGraph state machine, query routing, query decomposition, hybrid retrieval invocation, legal sufficiency judging, self-reflection loops, optional CrewAI analysis, citation-grounded Persian answer generation, and multi-turn memory. Use when building or modifying Agentic RAG, LangGraph, CrewAI, L-MARS-style reasoning, verification loops, or formal Persian legal answer generation.
---

# Persian Legal Agentic Core

## Overview

Build the reasoning core that turns a Persian legal question into a verified, citation-grounded answer. The core must not directly depend on Qdrant, Neo4j, OpenAI, CrewAI, or any specific model; use ports from Phase 1 and the architecture skill.

## Prerequisites

Use `$persian-legal-graphrag-ingestion` first if `HybridRetrieverPort` or equivalent retrieval contract does not exist. Use `$persian-legal-architecture` if ports and adapters are not established.

## State Contract

Define a typed state with at least:

```text
user_query
intent
decomposed_queries
retrieved_context
draft_response
verification_feedback
is_valid
chat_history
citations
retry_count
```

Read `references/agentic-core-contracts.md` before implementing.

## Required Nodes

- `router_node`: classify intent as legal advice, document analysis, general chat, out-of-scope, or lawyer recommendation handoff.
- `decompose_query_node`: split complex Persian legal questions into atomic retrieval queries.
- `retrieval_node`: call `HybridRetrieverPort` for each subquery.
- `judge_node`: verify factual sufficiency, temporal validity, jurisdiction, citation coverage, and legal caution.
- `crew_analysis_node`: optional adapter-backed CrewAI debate for complex disputes.
- `generation_node`: produce formal Persian answer with explicit citations and limitations.

## Graph Rules

Use a bounded self-reflection loop:

```text
router -> decompose -> retrieve -> judge
judge valid -> generate -> end
judge invalid and retry_count < max -> decompose or retrieve
judge invalid and retry_count >= max -> generate limited answer with insufficiency warning
```

Do not loop indefinitely.

## Answer Policy

Generated answers must:

- Be in formal Persian.
- Cite retrieved legal sources explicitly.
- Distinguish law-backed statements from reasoning or practical caution.
- Warn when context is insufficient, stale, outside Iranian jurisdiction, or not legal advice.
- Avoid pretending to know facts not present in the retrieved context.

## Acceptance Checks

- LangGraph node functions are individually testable.
- The graph can run with fake `LLMPort` and fake `HybridRetrieverPort`.
- Invalid retrieval context triggers re-retrieval or limited answer behavior.
- Memory/checkpointing is configurable and not hard-coded to a specific storage provider.
- CrewAI is optional and wrapped behind an adapter so the core graph works without it.
