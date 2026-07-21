# Persian Legal Assistant

The repository contains the ingestion/crawler utilities plus a provider-neutral
legal research application and a constrained Deep Agents runtime. The agent
searches Qdrant, expands only known Neo4j entity IDs, validates its cited source
IDs, and produces a formal Persian answer or an explicit insufficient-evidence
warning.

## Legal research agent

The implementation follows `interfaces -> application -> domain` and
`infrastructure -> application -> domain`. Deep Agents, OpenAI, Qdrant, and
Neo4j are isolated in infrastructure adapters; application services depend only
on typed ports.

Install the agent and start its data services:

```bash
uv sync --extra agent --extra dev
docker compose up -d neo4j qdrant
cp .env.example .env
```

Set `OPENAI_API_KEY` and the Neo4j credentials in `.env`. The Qdrant graph
collection must already contain embeddings created by
`scripts/embed_neo4j_nodes_batch.py`, using the same embedding model and
dimensions configured for query embedding.

Run one grounded question from the host machine:

```bash
set -a; source .env; set +a
QDRANT_URL="http://localhost:${QDRANT_HOST_PORT:-6333}" \
NEO4J_URI="bolt://localhost:${NEO4J_BOLT_HOST_PORT:-7687}" \
uv run --extra agent legal-assistant-ask --json \
  "شرایط اعتبار قراردادهای خصوصی بر اساس قانون مدنی چیست؟"
```

Important agent controls are environment-driven:

- `AGENT_MODEL_NAME` selects the OpenAI chat model.
- `GRAPH_RAG_QDRANT_COLLECTION` selects the graph-vector collection.
- `AGENT_MAX_TOOL_CALLS`, `AGENT_MAX_SEARCH_RESULTS`,
  `AGENT_MAX_GRAPH_DEPTH`, and `AGENT_MAX_GRAPH_RESULTS` bound research.
- `OPENAI_USE_RESPONSES_API=false` keeps the default Chat Completions path;
  opt in explicitly if required by the selected model.

The runtime exposes only two custom read tools: semantic legal-source search
and allowlisted graph expansion. Built-in file writes, deletion, shell
execution, broad filesystem reads, and subagents are disabled. Skills are
packaged under `infrastructure/agents/skills/` and loaded into an ephemeral
state filesystem for each invocation.

Run the network-free unit suite and static checks with:

```bash
uv run --extra agent --extra dev pytest -q
uv run --extra agent --extra dev pyrefly check
```

Install the crawler dependencies before running scripts under `scripts/`:

```bash
uv sync --extra crawlers
```

The browser-backed Dadrah crawler additionally needs Chromium:

```bash
uv run playwright install chromium
```

## Neo4j

Start the local graph database:

```bash
cp .env.example .env
docker compose up -d neo4j
```

Import the Dadrah consultation graph:

```bash
set -a; source .env; set +a
NEO4J_URI="bolt://localhost:${NEO4J_BOLT_HOST_PORT:-7687}" \
  python scripts/import_dadrah_to_neo4j.py data/import/dadrah_output_v2
```

Import Dadrah lawyer profiles idempotently:

```bash
set -a; source .env; set +a
NEO4J_URI="bolt://localhost:${NEO4J_BOLT_HOST_PORT:-7687}" \
  python scripts/import_lawyers_to_neo4j.py data/lawyers.jsonl
```

Import NovinLaw crawler graphs:

```bash
python scripts/import_novinlaw_to_neo4j.py \
  novinlaw_output novinlaw_unanimity_output --dry-run
```

The importers use stable identifiers, uniqueness constraints, and Cypher
`MERGE`, so rerunning them updates existing nodes without duplicating records.

### Embed Neo4j nodes for GraphRAG

The manual embedding script uses OpenAI's asynchronous Batch API and stores the
resulting vectors in Qdrant. By default it embeds text-bearing `Question`,
`Answer`, `Article`, `Note`, and `UnanimityDecision` nodes with
`text-embedding-3-large` at 3,072 dimensions. It does not embed container/index
nodes or duplicate full law documents whose articles are already represented.
Dadrah questions and answers may contain personal information; review your data
handling requirements before submitting them to an external API. Omit those
labels with `--labels Article Note UnanimityDecision` when appropriate.

Install both graph and ingestion dependencies, start Neo4j and Qdrant, and load
the environment:

```bash
uv sync --extra ai --extra ingestion
docker compose up -d neo4j qdrant
set -a; source .env; set +a
```

Prepare local Batch API request files. Start with a small sample if desired:

```bash
NEO4J_URI="bolt://localhost:${NEO4J_BOLT_HOST_PORT:-7687}" \
  python scripts/embed_neo4j_nodes_batch.py prepare --limit 100
```

Review `data/import/graph_embedding_batch/state.json`, then submit the paid
asynchronous jobs manually:

```bash
python scripts/embed_neo4j_nodes_batch.py submit
python scripts/embed_neo4j_nodes_batch.py status
```

If a job fails validation because the organization-wide enqueued-token limit
was full, wait for the other jobs to finish and create a new attempt from the
same uploaded request file. The command defaults to at most 2.9 million tokens
per retry wave, deferring excess failed shards until it is run again:

```bash
python scripts/embed_neo4j_nodes_batch.py retry \
  --work-dir data/import/graph_embedding_batch_full
```

To retry only selected failed jobs, repeat `--batch-id`:

```bash
python scripts/embed_neo4j_nodes_batch.py retry \
  --work-dir data/import/graph_embedding_batch_full \
  --batch-id batch_example_1 \
  --batch-id batch_example_2
```

The previous IDs and validation errors remain recorded under
`previous_attempts` in `state.json`.

After every batch reports `completed`, download its results and idempotently
upsert them into the `legal_graph_nodes` Qdrant collection:

```bash
QDRANT_URL="http://localhost:${QDRANT_HOST_PORT:-6333}" \
  python scripts/embed_neo4j_nodes_batch.py collect
```

The script can be rerun after interruption: submitted jobs are not resubmitted,
and collected Qdrant points use deterministic IDs. To prepare the complete
graph after a sample run, use a different `--work-dir`, or prepare again with
`--force` after intentionally removing/replacing the sample collection.

## Django PDF ingestion and Qdrant

The `LegalFile` Django model stores `id`, `title`, `file_url`, and
`local_address_file`, plus ingestion status fields. It is registered in Django
admin. The ingestion command reads the public four-field manifest and
automatically joins `files_metadata.jsonl` beside it to obtain stable IDs and
downloaded paths.

```bash
uv sync --extra api --extra ingestion
python manage.py migrate
docker compose up -d qdrant

set -a; source .env; set +a
QDRANT_URL="http://localhost:${QDRANT_HOST_PORT:-6333}" \
  python manage.py ingest_legal_files \
  novinlaw_files_output/files.jsonl --limit 10
```

For a credential-free local integration test, use deterministic hashing
embeddings in a separate collection:

```bash
set -a; source .env; set +a
DB_ENGINE=sqlite EMBEDDING_PROVIDER=hashing EMBEDDING_DIMENSIONS=384 \
LEGAL_FILES_QDRANT_COLLECTION=novinlaw_legal_files_test \
QDRANT_URL="http://localhost:${QDRANT_HOST_PORT:-6333}" \
  python manage.py ingest_legal_files \
  novinlaw_files_output/files.jsonl --limit 10
```

Rerunning the command updates Django rows and replaces each document's Qdrant
points, so it does not duplicate records. Scanned PDFs with no extractable text
are indexed using their title; add an OCR-backed extractor later for full-text
indexing of image-only PDFs. Hashing embeddings are intended only for local
pipeline verification; use `EMBEDDING_PROVIDER=openai` with a valid key for the
production semantic index.
