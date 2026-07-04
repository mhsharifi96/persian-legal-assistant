---
name: persian-legal-evaluation-recommender
description: Implement Phase 3 of a Persian legal assistant: lawyer recommendation, hybrid scoring with embeddings and success metrics, mock or repository-backed Iranian lawyer datasets, RAGAS evaluation, legal hallucination checks, faithfulness, context precision, answer relevancy, aspect critic metrics, and Persian-capable judge LLM integration. Use when building recommendation or evaluation modules for the thesis legal QA system.
---

# Persian Legal Evaluation Recommender

## Overview

Complete the service loop for the thesis system by recommending relevant lawyers and evaluating the assistant with RAGAS-style metrics. Keep recommendation data sources, embedding models, judge LLMs, and evaluation stores replaceable through ports.

## Prerequisites

Use `$persian-legal-architecture` for repository boundaries. Use `$persian-legal-agentic-core` when evaluating generated legal answers from Phase 2.

## Lawyer Recommendation

Implement recommendation as an application service:

```text
Analyze legal intent -> embed intent -> fetch lawyers -> score candidates -> return top N
```

Required lawyer fields:

```text
lawyer_id, full_name, specialties, location, success_rate
```

Use `EmbeddingModelPort`, not direct model calls. Default embedding model may remain `MCINext/Hakim-small`, but it must be configurable.

## Scoring

Start with a transparent weighted score:

```text
final_score = semantic_weight * cosine_similarity + success_weight * normalized_success_rate + location_weight * location_match
```

Document it as a practical approximation of multi-objective ranking. Do not claim a full AGE-MOEA implementation unless actually implemented.

## Evaluation

Build an evaluation pipeline around:

- `question`
- `answer`
- `contexts`
- `ground_truth`
- generated citations
- judge feedback

RAGAS metrics:

- `context_precision`
- `faithfulness`
- `answer_relevancy`
- aspect critic for legal sufficiency and citation grounding

Read `references/evaluation-recommender-contracts.md` before implementation.

## Acceptance Checks

- Recommendation service works with a Pandas mock repository and can later use SQL or API repository without changing service logic.
- Scoring weights are configurable.
- Evaluation data can be loaded from local JSONL/CSV and converted to RAGAS dataset objects.
- Judge LLM is injected through a port or provider wrapper.
- Output includes an aggregated Pandas DataFrame and a concise summary report.
