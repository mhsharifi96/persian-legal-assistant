---
name: legal-research-routing
description: Use for Iranian legal questions that require semantic retrieval, graph expansion, evidence refinement, or comparison of laws and decisions.
---

# Legal research routing

1. Restate the legal issue as one precise Persian search query.
2. Call `semantic_search_legal_sources` before making any substantive legal claim.
3. Inspect returned `entity_id`, `source_type`, `authority`, and text.
4. Call `expand_legal_graph` only with entity IDs returned by semantic search and only when relationships can materially improve the answer.
5. If the first search misses the issue, refine the semantic query once. Do not repeat an identical search.
6. Stop research before the tool budget is exhausted and write the answer from the collected evidence.

Never request raw Cypher, shell execution, filesystem writes, or a subagent.
