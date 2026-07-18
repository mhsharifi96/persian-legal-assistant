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

## Oversized Article Splitting

When an article's (or note's) text exceeds the embedding model's token budget, split it recursively instead of embedding one oversized chunk:

- Split on paragraph/sentence boundaries first, falling back to a fixed token window with overlap (e.g. 10-15%) only if no natural boundary exists.
- Every subchunk keeps the full parent hierarchy metadata (`book`, `bab`, `fasl`, `article_number`, `note_number`) unchanged.
- Add `part_index` and `part_count` to chunk metadata so subchunks of the same article/note are identifiable and can be reassembled or deduplicated at retrieval/generation time.
- Chunk IDs must stay unique per subchunk (include `part_index` in the ID derivation) while remaining deterministic.
- Never split so finely that a subchunk loses the sentence containing the legal obligation, deadline, or penalty it is meant to convey.

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
4. Expand graph neighborhood by 1 or 2 hops using relation allowlist, with a fan-out limit per hop (e.g. cap neighbors per source node) so a heavily-referenced concept entity cannot flood the result set.
5. Merge, deduplicate, and rank contexts. Vector cosine-similarity scores and graph-expansion scores are not on the same scale and must never be sorted together as raw values — fuse by rank, not by score. Use Reciprocal Rank Fusion (`fused_score = sum(1 / (k + rank))` across each source's ranked list, `k ~= 60`) or an equivalent rank-based method, and store the fused score on the returned context rather than the original per-source score.
6. Return context objects with citations and hierarchy.

## Failure Handling

- Parser failures should include source URI and page range where available.
- Embedding failures should fail the batch item, not silently drop it. Embed in bounded sub-batches (not one call for an entire document) so one failing item does not invalidate chunks that already embedded successfully.
- Qdrant and Neo4j writes should be idempotent.
- LLM JSON parsing should retry once with a repair prompt, then store a structured error record. The repair prompt must include the specific validation failure (which field, which invalid value) alongside the original response — a generic "fix this JSON" retry with no diagnostic context has a much lower repair success rate.
- Graph extraction (and any other per-chunk ingestion step) must isolate failures per chunk: a chunk that fails extraction after the repair retry should be recorded as a structured error (`document_id`, `chunk_id`, `stage`, `error_message`) and skipped, not allowed to abort the rest of the document's ingestion run. Partial graph/vector writes that already succeeded for earlier chunks must not be silently lost when a later chunk fails.
- Structured error records should be persisted somewhere queryable (e.g. an `IngestionErrorSink`/`EvaluationRepository`-style port), not just raised and logged, so failed chunks can be reprocessed later.
