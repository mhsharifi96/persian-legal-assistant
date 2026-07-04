# Phase 2 Agentic Core Contracts

## State Shape

Use `TypedDict`, Pydantic, or LangGraph-compatible state. Example:

```python
class LegalQAState(TypedDict, total=False):
    user_query: str
    intent: Literal["legal_advice", "document_analysis", "general_chat", "out_of_scope", "lawyer_recommendation"]
    decomposed_queries: list[str]
    retrieved_context: list[RetrievedContext]
    draft_response: str
    verification_feedback: list[str]
    is_valid: bool
    chat_history: list[dict]
    citations: list[dict]
    retry_count: int
```

Keep state serializable for checkpointing.

## Router Output

Structured router output:

```json
{
  "intent": "legal_advice",
  "confidence": 0.87,
  "reason": "Question asks about legal rights under Iranian law."
}
```

Route general chat to a minimal non-legal response. Route out-of-scope questions to a refusal or clarification path.

## Query Decomposition

For complex Persian questions, produce atomic retrieval queries:

- Identify legal domain: contract, family, labor, criminal, civil procedure, commercial.
- Extract parties, dates, jurisdiction, demanded outcome, and named laws.
- Generate 2 to 6 focused search queries.
- Preserve user facts separately from legal questions.

## Judge Criteria

The judge should set `is_valid=False` if:

- retrieved context lacks a relevant legal source;
- citations do not support the draft answer;
- the answer depends on a date or jurisdiction not present in context;
- context conflicts and the answer does not mention uncertainty;
- the question asks for a lawyer recommendation but no analyzed legal intent exists;
- the generated answer contains uncited legal obligations, deadlines, penalties, or rights.

Judge output:

```json
{
  "is_valid": false,
  "feedback": [
    "No cited source establishes the deadline.",
    "Retrieved context is about labor law but question is about family law."
  ],
  "next_action": "retrieve_more"
}
```

## Generation Contract

Formal Persian answer structure:

```text
خلاصه پاسخ:
...

مبنای قانونی:
- ...

تحلیل:
...

محدودیت و هشدار:
...
```

Use citations such as:

```text
[قانون مدنی، ماده ۱۰]
[قانون آیین دادرسی مدنی، ماده ۵۱۵، تبصره ۱]
```

## Ports

The graph should depend on:

```text
LLMPort
HybridRetrieverPort
CheckpointRepository or LangGraph checkpointer factory
Optional CrewAnalysisPort
```

Do not instantiate OpenAI clients, Qdrant clients, Neo4j drivers, or CrewAI crews inside node logic unless those are inside adapters.

## Testing

Use fake ports:

- fake retriever returns known contexts;
- fake judge LLM returns valid/invalid structured JSON;
- fake generator returns deterministic Persian text.

Test:

- happy path;
- insufficient context loop;
- max retry fallback;
- general chat route;
- out-of-scope route;
- citation preservation.
