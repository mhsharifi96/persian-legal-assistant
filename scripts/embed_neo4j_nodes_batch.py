#!/usr/bin/env python3
"""Embed text-bearing Neo4j nodes with the OpenAI Batch API.

The manual workflow is intentionally split into four main commands:

    prepare -> submit -> status -> collect

``prepare`` reads Neo4j and writes local JSONL request/manifest shards.
``submit`` uploads those shards and creates asynchronous OpenAI batches.
``status`` reports their current states. ``collect`` downloads completed
vectors and idempotently upserts them into Qdrant. ``retry`` creates new jobs
for shards whose previous Batch API validation failed.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import uuid
from array import array
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tiktoken
from neo4j import GraphDatabase
from openai import OpenAI
from qdrant_client import QdrantClient, models


DEFAULT_LABELS = ("Question", "Answer", "Article", "Note", "UnanimityDecision")
DEFAULT_WORK_DIR = Path("data/import/graph_embedding_batch")
STATE_FILE = "state.json"
POINT_NAMESPACE = uuid.UUID("f77e92a2-6314-4cf6-a31c-42009028ab0b")


@dataclass(frozen=True)
class GraphNode:
    entity_id: str
    labels: tuple[str, ...]
    title: str
    text: str
    url: str
    node_type: str
    source_datasets: tuple[str, ...]


@dataclass(frozen=True)
class TextChunk:
    entity_id: str
    point_id: str
    labels: tuple[str, ...]
    title: str
    text: str
    url: str
    node_type: str
    source_datasets: tuple[str, ...]
    chunk_index: int
    chunk_count: int
    token_count: int


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def require_env(name: str) -> str:
    value = env(name).strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def read_state(work_dir: Path) -> dict[str, Any]:
    path = work_dir / STATE_FILE
    if not path.is_file():
        raise FileNotFoundError(f"State file not found: {path}; run prepare first")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Invalid state file: {path}")
    return value


def neo4j_nodes(args: argparse.Namespace) -> Iterator[GraphNode]:
    query = """
    MATCH (node:LegalEntity)
    WHERE trim(coalesce(node.text, '')) <> ''
      AND any(label IN labels(node) WHERE label IN $labels)
    RETURN node.entity_id AS entity_id,
           labels(node) AS labels,
           coalesce(node.title, node.name, '') AS title,
           node.text AS text,
           coalesce(node.url, node.page_url, '') AS url,
           coalesce(node.node_type, node.type, '') AS node_type,
           coalesce(node.source_datasets, []) AS source_datasets
    ORDER BY node.entity_id
    """
    parameters: dict[str, Any] = {"labels": args.labels}
    if args.limit is not None:
        query += " LIMIT $limit"
        parameters["limit"] = args.limit

    driver = GraphDatabase.driver(
        args.neo4j_uri,
        auth=(args.neo4j_username, args.neo4j_password),
    )
    try:
        driver.verify_connectivity()
        with driver.session(database=args.neo4j_database, fetch_size=500) as session:
            for record in session.run(query, **parameters):
                yield GraphNode(
                    entity_id=str(record["entity_id"]),
                    labels=tuple(sorted(str(value) for value in record["labels"])),
                    title=str(record["title"] or "").strip(),
                    text=str(record["text"] or "").strip(),
                    url=str(record["url"] or "").strip(),
                    node_type=str(record["node_type"] or "").strip(),
                    source_datasets=tuple(
                        str(value) for value in record["source_datasets"]
                    ),
                )
    finally:
        driver.close()


def chunk_node(
    node: GraphNode,
    *,
    encoding: Any,
    max_tokens: int,
    overlap_tokens: int,
    collection: str,
) -> list[TextChunk]:
    heading_parts = []
    if node.title:
        heading_parts.append(f"عنوان: {node.title}")
    semantic_labels = [
        label
        for label in node.labels
        if label not in {"LegalEntity", "DadrahNode", "LawNode", "Laws", "Unanimity"}
    ]
    if semantic_labels:
        heading_parts.append(f"نوع: {', '.join(semantic_labels)}")
    heading = "\n".join(heading_parts)
    text_tokens: list[int] = encoding.encode(node.text)
    heading_tokens: list[int] = encoding.encode(heading + "\n\n") if heading else []
    available = max_tokens - len(heading_tokens)
    if available <= 0:
        raise ValueError(f"Heading exceeds token limit for {node.entity_id}")
    if overlap_tokens >= available:
        raise ValueError("overlap_tokens must be smaller than available chunk tokens")

    pieces: list[list[int]] = []
    start = 0
    while start < len(text_tokens):
        end = min(start + available, len(text_tokens))
        pieces.append(text_tokens[start:end])
        if end == len(text_tokens):
            break
        start = end - overlap_tokens

    chunks: list[TextChunk] = []
    for index, piece in enumerate(pieces, start=1):
        text = f"{heading}\n\n{encoding.decode(piece)}" if heading else encoding.decode(piece)
        point_name = f"{collection}\0{node.entity_id}\0{index}"
        chunks.append(
            TextChunk(
                entity_id=node.entity_id,
                point_id=str(uuid.uuid5(POINT_NAMESPACE, point_name)),
                labels=node.labels,
                title=node.title,
                text=text,
                url=node.url,
                node_type=node.node_type,
                source_datasets=node.source_datasets,
                chunk_index=index,
                chunk_count=len(pieces),
                token_count=len(heading_tokens) + len(piece),
            )
        )
    return chunks


def chunk_stream(args: argparse.Namespace) -> Iterator[TextChunk]:
    encoding = tiktoken.encoding_for_model(args.model)
    for node in neo4j_nodes(args):
        yield from chunk_node(
            node,
            encoding=encoding,
            max_tokens=args.max_input_tokens,
            overlap_tokens=args.overlap_tokens,
            collection=args.collection,
        )


def open_shard(work_dir: Path, number: int) -> tuple[Any, Any, Path, Path]:
    request_path = work_dir / f"requests-{number:04d}.jsonl"
    manifest_path = work_dir / f"manifest-{number:04d}.jsonl"
    return (
        request_path.open("w", encoding="utf-8"),
        manifest_path.open("w", encoding="utf-8"),
        request_path,
        manifest_path,
    )


def prepare(args: argparse.Namespace) -> int:
    work_dir: Path = args.work_dir
    work_dir.mkdir(parents=True, exist_ok=True)
    state_path = work_dir / STATE_FILE
    if state_path.exists() and not args.force:
        raise FileExistsError(f"{state_path} exists; use --force to prepare again")

    shards: list[dict[str, Any]] = []
    request_handle = None
    manifest_handle = None
    request_path = None
    manifest_path = None
    shard_number = 0
    shard_count = 0
    total_chunks = 0
    total_tokens = 0
    entity_ids: set[str] = set()

    try:
        for chunk in chunk_stream(args):
            if request_handle is None or shard_count >= args.shard_inputs:
                if request_handle is not None:
                    request_handle.close()
                    manifest_handle.close()
                    shards.append(
                        {
                            "request_file": request_path.name,
                            "manifest_file": manifest_path.name,
                            "inputs": shard_count,
                            "batch_id": None,
                            "input_file_id": None,
                            "status": "prepared",
                            "collected": False,
                        }
                    )
                shard_number += 1
                shard_count = 0
                request_handle, manifest_handle, request_path, manifest_path = open_shard(
                    work_dir, shard_number
                )

            custom_id = f"graph-{shard_number:04d}-{shard_count + 1:06d}"
            request = {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/embeddings",
                "body": {
                    "model": args.model,
                    "input": chunk.text,
                    "dimensions": args.dimensions,
                    "encoding_format": "base64",
                },
            }
            manifest = {
                "custom_id": custom_id,
                "point_id": chunk.point_id,
                "entity_id": chunk.entity_id,
                "labels": chunk.labels,
                "title": chunk.title,
                "text": chunk.text,
                "url": chunk.url,
                "node_type": chunk.node_type,
                "source_datasets": chunk.source_datasets,
                "chunk_index": chunk.chunk_index,
                "chunk_count": chunk.chunk_count,
                "token_count": chunk.token_count,
                "embedding_model": args.model,
                "embedding_dimensions": args.dimensions,
            }
            request_handle.write(json.dumps(request, ensure_ascii=False) + "\n")
            manifest_handle.write(json.dumps(manifest, ensure_ascii=False) + "\n")
            shard_count += 1
            total_chunks += 1
            total_tokens += chunk.token_count
            entity_ids.add(chunk.entity_id)
    finally:
        if request_handle is not None and not request_handle.closed:
            request_handle.close()
        if manifest_handle is not None and not manifest_handle.closed:
            manifest_handle.close()

    if shard_count and request_path is not None and manifest_path is not None:
        shards.append(
            {
                "request_file": request_path.name,
                "manifest_file": manifest_path.name,
                "inputs": shard_count,
                "batch_id": None,
                "input_file_id": None,
                "status": "prepared",
                "collected": False,
            }
        )
    if not shards:
        raise RuntimeError("No matching text-bearing Neo4j nodes were found")

    state = {
        "version": 1,
        "model": args.model,
        "dimensions": args.dimensions,
        "collection": args.collection,
        "labels": args.labels,
        "max_input_tokens": args.max_input_tokens,
        "overlap_tokens": args.overlap_tokens,
        "entities": len(entity_ids),
        "chunks": total_chunks,
        "tokens": total_tokens,
        "shards": shards,
    }
    write_json(state_path, state)
    print(
        f"Prepared {len(entity_ids):,} nodes as {total_chunks:,} embedding inputs "
        f"({total_tokens:,} tokens) in {len(shards)} shard(s)."
    )
    print(f"Review {state_path}, then run the submit command.")
    return 0


def openai_client(args: argparse.Namespace) -> OpenAI:
    return OpenAI(api_key=require_env("OPENAI_API_KEY"), base_url=args.openai_base or None)


def submit(args: argparse.Namespace) -> int:
    state = read_state(args.work_dir)
    client = openai_client(args)
    submitted = 0
    for shard in state["shards"]:
        if shard.get("batch_id"):
            continue
        request_path = args.work_dir / shard["request_file"]
        with request_path.open("rb") as handle:
            uploaded = client.files.create(file=handle, purpose="batch")
        batch = client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/embeddings",
            completion_window="24h",
            metadata={"description": "Persian legal graph node embeddings"},
        )
        shard["input_file_id"] = uploaded.id
        shard["batch_id"] = batch.id
        shard["status"] = batch.status
        submitted += 1
        write_json(args.work_dir / STATE_FILE, state)
        print(f"Submitted {shard['request_file']}: {batch.id} ({batch.status})")
    print(f"Submitted {submitted} new batch(es).")
    return 0


def retry(args: argparse.Namespace) -> int:
    state = refresh_status(args, quiet=True)
    client = openai_client(args)
    retried = 0
    enqueued_tokens = 0
    selected_ids = set(args.batch_id or ())
    failed_shards = [shard for shard in state["shards"] if shard.get("status") == "failed"]
    failed_ids = {shard.get("batch_id") for shard in failed_shards}
    unknown_ids = selected_ids - failed_ids
    if unknown_ids:
        raise ValueError(
            "Requested batch IDs were not failed jobs in this state: "
            + ", ".join(sorted(unknown_ids))
        )
    for shard in failed_shards:
        old_batch_id = shard.get("batch_id")
        if selected_ids and old_batch_id not in selected_ids:
            continue
        shard_tokens = sum(
            int(row["token_count"])
            for row in read_jsonl(args.work_dir / shard["manifest_file"])
        )
        if enqueued_tokens + shard_tokens > args.max_enqueued_tokens:
            print(
                f"Deferred {shard['request_file']} ({shard_tokens:,} tokens): "
                f"this retry wave is capped at {args.max_enqueued_tokens:,} tokens"
            )
            continue
        input_file_id = shard.get("input_file_id")
        if not input_file_id:
            raise RuntimeError(
                f"Failed shard {shard['request_file']} has no input_file_id"
            )
        attempts = shard.setdefault("previous_attempts", [])
        attempts.append(
            {
                "batch_id": old_batch_id,
                "input_file_id": input_file_id,
                "status": shard.get("status"),
                "errors": shard.get("errors"),
            }
        )
        batch = client.batches.create(
            input_file_id=input_file_id,
            endpoint="/v1/embeddings",
            completion_window="24h",
            metadata={"description": "Retry Persian legal graph node embeddings"},
        )
        shard["batch_id"] = batch.id
        shard["status"] = batch.status
        shard["output_file_id"] = None
        shard["error_file_id"] = None
        shard["request_counts"] = None
        shard["errors"] = None
        retried += 1
        enqueued_tokens += shard_tokens
        write_json(args.work_dir / STATE_FILE, state)
        print(
            f"Retried {shard['request_file']}: {old_batch_id} -> "
            f"{batch.id} ({batch.status}, {shard_tokens:,} tokens)"
        )
    print(
        f"Retried {retried} failed batch(es), enqueueing {enqueued_tokens:,} tokens."
    )
    return 0


def refresh_status(args: argparse.Namespace, *, quiet: bool = False) -> dict[str, Any]:
    state = read_state(args.work_dir)
    client = openai_client(args)
    for shard in state["shards"]:
        batch_id = shard.get("batch_id")
        if not batch_id:
            if not quiet:
                print(f"{shard['request_file']}: not submitted")
            continue
        batch = client.batches.retrieve(batch_id)
        shard["status"] = batch.status
        shard["output_file_id"] = batch.output_file_id
        shard["error_file_id"] = batch.error_file_id
        shard["errors"] = (
            batch.errors.model_dump(mode="json") if batch.errors is not None else None
        )
        counts = batch.request_counts
        shard["request_counts"] = (
            {
                "total": counts.total,
                "completed": counts.completed,
                "failed": counts.failed,
            }
            if counts is not None
            else None
        )
        if not quiet:
            print(f"{batch_id}: {batch.status} {shard['request_counts'] or ''}")
    write_json(args.work_dir / STATE_FILE, state)
    return state


def status(args: argparse.Namespace) -> int:
    refresh_status(args)
    return 0


def ensure_collection(client: QdrantClient, name: str, dimensions: int) -> None:
    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(
                size=dimensions,
                distance=models.Distance.COSINE,
            ),
        )
        client.create_payload_index(
            collection_name=name,
            field_name="entity_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True,
        )
        return
    info = client.get_collection(name)
    existing_size = getattr(info.config.params.vectors, "size", None)
    if existing_size is not None and existing_size != dimensions:
        raise ValueError(
            f"Qdrant collection {name!r} has {existing_size} dimensions; "
            f"expected {dimensions}"
        )


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Expected object at {path}:{line_number}")
            yield value


def decode_embedding(value: str, dimensions: int) -> list[float]:
    raw = base64.b64decode(value, validate=True)
    vector = array("f")
    vector.frombytes(raw)
    if sys.byteorder != "little":
        vector.byteswap()
    if len(vector) != dimensions:
        raise ValueError(f"Embedding has {len(vector)} dimensions; expected {dimensions}")
    return vector.tolist()


def point_batches(items: Iterable[models.PointStruct], size: int) -> Iterator[list[models.PointStruct]]:
    batch: list[models.PointStruct] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def output_points(
    output_path: Path,
    manifests: dict[str, dict[str, Any]],
    dimensions: int,
    failures: list[dict[str, Any]],
) -> Iterator[models.PointStruct]:
    for result in read_jsonl(output_path):
        custom_id = str(result.get("custom_id") or "")
        manifest = manifests.get(custom_id)
        if manifest is None:
            raise ValueError(f"Unknown custom_id in output: {custom_id}")
        response = result.get("response")
        if not isinstance(response, dict) or response.get("status_code") != 200:
            failures.append(result)
            continue
        body = response.get("body")
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or len(data) != 1:
            failures.append(result)
            continue
        encoded = data[0].get("embedding") if isinstance(data[0], dict) else None
        if not isinstance(encoded, str):
            failures.append(result)
            continue
        payload = {key: value for key, value in manifest.items() if key != "point_id"}
        yield models.PointStruct(
            id=manifest["point_id"],
            vector=decode_embedding(encoded, dimensions),
            payload=payload,
        )


def collect(args: argparse.Namespace) -> int:
    state = refresh_status(args, quiet=True)
    client = openai_client(args)
    qdrant = QdrantClient(url=args.qdrant_url, api_key=args.qdrant_api_key or None)
    ensure_collection(qdrant, state["collection"], state["dimensions"])
    collected = 0

    for shard in state["shards"]:
        if shard.get("collected") or shard.get("status") != "completed":
            continue
        output_file_id = shard.get("output_file_id")
        if not output_file_id:
            print(f"Skipping {shard['batch_id']}: completed without an output file")
            continue
        output_path = args.work_dir / shard["request_file"].replace("requests-", "output-")
        output_path.write_text(client.files.content(output_file_id).text, encoding="utf-8")
        manifests = {
            row["custom_id"]: row
            for row in read_jsonl(args.work_dir / shard["manifest_file"])
        }
        failures: list[dict[str, Any]] = []
        point_count = 0
        for points in point_batches(
            output_points(output_path, manifests, state["dimensions"], failures),
            args.qdrant_upsert_size,
        ):
            qdrant.upsert(
                collection_name=state["collection"], points=points, wait=True
            )
            point_count += len(points)
        error_file_id = shard.get("error_file_id")
        if error_file_id:
            error_path = output_path.with_name(output_path.stem + "-api-errors.jsonl")
            error_path.write_text(
                client.files.content(error_file_id).text, encoding="utf-8"
            )
        if failures:
            failure_path = output_path.with_name(output_path.stem + "-failures.jsonl")
            failure_path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in failures),
                encoding="utf-8",
            )
        failure_count = len(manifests) - point_count
        shard["collected"] = True
        shard["points_upserted"] = point_count
        shard["failures"] = failure_count
        write_json(args.work_dir / STATE_FILE, state)
        collected += 1
        print(
            f"Collected {shard['batch_id']}: {point_count:,} points, "
            f"{failure_count:,} failures"
        )
    print(f"Collected {collected} newly completed batch(es).")
    return 0


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--openai-base", default=env("OPENAI_API_BASE"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="Create Batch API JSONL files")
    add_common_arguments(prepare_parser)
    prepare_parser.add_argument(
        "--neo4j-uri", default=env("NEO4J_URI", "bolt://localhost:7687")
    )
    prepare_parser.add_argument(
        "--neo4j-username", default=env("NEO4J_USERNAME", "neo4j")
    )
    prepare_parser.add_argument(
        "--neo4j-password", default=env("NEO4J_PASSWORD", "please-change")
    )
    prepare_parser.add_argument(
        "--neo4j-database", default=env("NEO4J_DATABASE", "neo4j")
    )
    prepare_parser.add_argument(
        "--collection", default=env("GRAPH_RAG_QDRANT_COLLECTION", "legal_graph_nodes")
    )
    prepare_parser.add_argument(
        "--model", default=env("EMBEDDING_MODEL_NAME", "text-embedding-3-large")
    )
    prepare_parser.add_argument(
        "--dimensions", type=int, default=int(env("EMBEDDING_DIMENSIONS", "3072"))
    )
    prepare_parser.add_argument("--labels", nargs="+", default=list(DEFAULT_LABELS))
    prepare_parser.add_argument("--max-input-tokens", type=int, default=8000)
    prepare_parser.add_argument("--overlap-tokens", type=int, default=200)
    prepare_parser.add_argument("--shard-inputs", type=int, default=2000)
    prepare_parser.add_argument("--limit", type=int)
    prepare_parser.add_argument("--force", action="store_true")
    prepare_parser.set_defaults(handler=prepare)

    submit_parser = subparsers.add_parser("submit", help="Upload and submit prepared files")
    add_common_arguments(submit_parser)
    submit_parser.set_defaults(handler=submit)

    status_parser = subparsers.add_parser("status", help="Refresh OpenAI batch statuses")
    add_common_arguments(status_parser)
    status_parser.set_defaults(handler=status)

    retry_parser = subparsers.add_parser(
        "retry", help="Create new jobs for failed batch shards"
    )
    add_common_arguments(retry_parser)
    retry_parser.add_argument(
        "--batch-id",
        action="append",
        help="Retry only this failed batch ID; may be supplied more than once",
    )
    retry_parser.add_argument(
        "--max-enqueued-tokens",
        type=int,
        default=2_900_000,
        help="Maximum tokens to submit in one retry wave (default: 2900000)",
    )
    retry_parser.set_defaults(handler=retry)

    collect_parser = subparsers.add_parser(
        "collect", help="Download completed vectors and upsert them into Qdrant"
    )
    add_common_arguments(collect_parser)
    collect_parser.add_argument(
        "--qdrant-url", default=env("QDRANT_URL", "http://localhost:6333")
    )
    collect_parser.add_argument("--qdrant-api-key", default=env("QDRANT_API_KEY"))
    collect_parser.add_argument("--qdrant-upsert-size", type=int, default=128)
    collect_parser.set_defaults(handler=collect)
    return parser


def validate_args(args: argparse.Namespace) -> None:
    for name in (
        "dimensions",
        "max_input_tokens",
        "shard_inputs",
        "qdrant_upsert_size",
        "max_enqueued_tokens",
    ):
        value = getattr(args, name, None)
        if value is not None and value <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be greater than zero")
    overlap = getattr(args, "overlap_tokens", None)
    if overlap is not None and overlap < 0:
        raise ValueError("--overlap-tokens cannot be negative")
    limit = getattr(args, "limit", None)
    if limit is not None and limit <= 0:
        raise ValueError("--limit must be greater than zero")


def main() -> int:
    args = build_parser().parse_args()
    validate_args(args)
    return int(args.handler(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
