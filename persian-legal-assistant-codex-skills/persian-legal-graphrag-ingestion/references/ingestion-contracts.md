# Phase 1 Ingestion Contracts

## Persian Legal Hierarchy

Recognize these structures in order of broadest to narrowest:

```text
کتاب
باب
فصل
مبحث
گفتار
ماده
تبصره
بند
جزء
```

The minimum required hierarchy is `کتاب`, `باب`, `فصل`, `ماده`, and `تبصره`. Add `مبحث`, `گفتار`, `بند`, and `جزء` when present.

## Regex Guidance

Handle Persian and Arabic digits, optional punctuation, and spacing differences.

Useful patterns:

```python
ARTICLE_RE = r"(?m)^\s*ماده\s+([۰-۹0-9]+)\s*[-:ـ]?"
NOTE_RE = r"(?m)^\s*تبصره(?:\s+([۰-۹0-9]+))?\s*[-:ـ]?"
BOOK_RE = r"(?m)^\s*کتاب\s+(.+)$"
BAB_RE = r"(?m)^\s*باب\s+(.+)$"
FASL_RE = r"(?m)^\s*فصل\s+(.+)$"
```

Normalize digits for IDs, but preserve original text for citations.

## Chunk Metadata Schema

Each `LegalChunk.metadata` should include:

```json
{
  "document_id": "civil-code",
  "source_uri": "file:///laws/civil-code.pdf",
  "jurisdiction": "IR",
  "law_title": "قانون مدنی",
  "document_type": "law",
  "book": "کتاب اول",
  "bab": "باب اول",
  "fasl": "فصل دوم",
  "article_number": "10",
  "note_number": null,
  "effective_date": null,
  "publication_date": null,
  "version": null,
  "page_start": 12,
  "page_end": 13,
  "char_start": 1520,
  "char_end": 2250,
  "parser_name": "llamaparse",
  "chunking_strategy": "iranian_legal_hierarchical_v1"
}
```

## Chunking Rules

- Prefer article-level chunks.
- Keep short article notes with their parent article only if they are inseparable; otherwise emit note chunks with parent article metadata.
- If an article exceeds token limits, split recursively inside the article and keep article metadata on every subchunk.
- Never split in a way that loses parent hierarchy.
- Generate deterministic chunk IDs from document ID, hierarchy, and offsets.

## Knowledge Graph Extraction JSON

Require structured LLM output in this shape:

```json
{
  "entities": [
    {"id": "article:قانون-مدنی:10", "type": "Article", "name": "ماده ۱۰ قانون مدنی", "properties": {}}
  ],
  "relationships": [
    {"source_id": "article:...", "target_id": "concept:...", "type": "DEFINES", "properties": {}}
  ]
}
```

Validate:

- `type` is in the configured allowed labels.
- relationship endpoints exist or can be upserted as placeholder entities.
- no relationship type is free-form Persian prose.

## Hybrid Retrieval Algorithm

1. Embed query with `EmbeddingModelPort`.
2. Search vector store with filters such as jurisdiction, law_title, date, document_type.
3. Extract top chunk IDs and article IDs.
4. Expand graph neighborhood by 1 or 2 hops using relation allowlist.
5. Merge, deduplicate, and rank contexts.
6. Return context objects with citations and hierarchy.

## Failure Handling

- Parser failures should include source URI and page range where available.
- Embedding failures should fail the batch item, not silently drop it.
- Qdrant and Neo4j writes should be idempotent.
- LLM JSON parsing should retry once with a repair prompt, then store a structured error record.
