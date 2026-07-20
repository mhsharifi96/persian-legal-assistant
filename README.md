# Persian Legal Assistant

The previous domain-model application stack has been removed so the project can
be redesigned. The repository currently retains standalone collection and
Neo4j import utilities that do not depend on the removed domain models.

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
