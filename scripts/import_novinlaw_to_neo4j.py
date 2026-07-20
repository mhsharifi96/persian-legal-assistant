#!/usr/bin/env python3
"""Idempotently import NovinLaw crawler SQLite graphs into Neo4j.

The source SQLite databases are opened read-only. Nodes retain their stable
NovinLaw IDs and are merged as ``LegalEntity``/``NovinLawNode`` vertices.
Relations retain their original type and a deterministic key so multiple raw
references between the same pair of nodes are not collapsed.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sqlite3
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RELATION_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
LABEL_RE = re.compile(r"^[A-Z][A-Za-z0-9_]*$")

DATABASE_NAMES = {
    "laws": "novinlaw.sqlite3",
    "unanimity": "novinlaw_unanimity.sqlite3",
}

TYPE_LABELS: dict[str, dict[str, tuple[str, ...]]] = {
    "laws": {
        "index": ("Index",),
        "category": ("LegalCategory",),
        "law_group": ("Law", "LawGroup"),
        "document": ("Law",),
        "article": ("Article",),
        "note": ("Note",),
        "unresolved_reference": ("UnresolvedLegalReference",),
    },
    "unanimity": {
        "index": ("Index",),
        "year": ("DecisionYear",),
        "decision": ("LegalDecision", "UnanimityDecision"),
        "institution": ("Organization",),
        "legal_document": ("Law",),
        "legal_provision": ("LegalProvision",),
        "external_legal_document": ("ExternalLegalDocument",),
        "external_legal_provision": ("ExternalLegalProvision",),
        "unresolved_legal_reference": ("UnresolvedLegalReference",),
        "external_unanimity_decision": ("ExternalUnanimityDecision",),
    },
}

DATASET_LABELS = {
    "laws": "Laws",
    "unanimity": "Unanimity",
}


@dataclass(frozen=True)
class Dataset:
    name: str
    path: Path


@dataclass(frozen=True)
class DatasetStats:
    nodes: int
    relations: int
    node_types: dict[str, int]
    relation_types: dict[str, int]


def chunks(items: Iterable[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def resolve_database(path: Path, dataset: str) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.is_dir():
        resolved = resolved / DATABASE_NAMES[dataset]
    if not resolved.is_file():
        raise FileNotFoundError(f"{dataset} SQLite database not found: {resolved}")
    return resolved


def connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def validate_database(dataset: Dataset) -> DatasetStats:
    with connect_read_only(dataset.path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed for {dataset.path}: {integrity}")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not {"nodes", "relations"}.issubset(tables):
            raise RuntimeError(f"Expected nodes and relations tables in {dataset.path}")

        node_types = dict(
            connection.execute(
                "SELECT type, COUNT(*) FROM nodes GROUP BY type ORDER BY type"
            ).fetchall()
        )
        relation_types = dict(
            connection.execute(
                "SELECT relation_type, COUNT(*) FROM relations "
                "GROUP BY relation_type ORDER BY relation_type"
            ).fetchall()
        )
        invalid_relations = [kind for kind in relation_types if not RELATION_TYPE_RE.fullmatch(kind)]
        if invalid_relations:
            raise RuntimeError(
                f"Unsafe relation types in {dataset.path}: {', '.join(invalid_relations)}"
            )
        unknown_types = sorted(set(node_types) - set(TYPE_LABELS[dataset.name]))
        if unknown_types:
            raise RuntimeError(
                f"Unmapped node types in {dataset.path}: {', '.join(unknown_types)}"
            )
        return DatasetStats(
            nodes=sum(node_types.values()),
            relations=sum(relation_types.values()),
            node_types=node_types,
            relation_types=relation_types,
        )


def iter_nodes(dataset: Dataset) -> Iterator[dict[str, Any]]:
    with connect_read_only(dataset.path) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(nodes)")]
        query = f"SELECT {','.join(columns)} FROM nodes ORDER BY id"
        for row in connection.execute(query):
            values = {column: row[column] for column in columns}
            node_type = str(values.pop("type"))
            yield {
                "id": str(values.pop("id")),
                "dataset": dataset.name,
                "node_type": node_type,
                "properties": values,
            }


def relation_key(source_id: str, target_id: str, relation_type: str, raw_reference: str) -> str:
    payload = "\0".join((source_id, target_id, relation_type, raw_reference))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def iter_relations(dataset: Dataset) -> Iterator[dict[str, Any]]:
    with connect_read_only(dataset.path) as connection:
        for row in connection.execute(
            "SELECT source_id,target_id,relation_type,raw_reference,confidence,source_url "
            "FROM relations ORDER BY relation_type,source_id,target_id,raw_reference"
        ):
            raw_reference = str(row["raw_reference"] or "")
            relation_type = str(row["relation_type"])
            source_id = str(row["source_id"])
            target_id = str(row["target_id"])
            yield {
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relation_type,
                "relation_key": relation_key(
                    source_id, target_id, relation_type, raw_reference
                ),
                "dataset": dataset.name,
                "raw_reference": raw_reference,
                "confidence": float(row["confidence"]),
                "source_url": str(row["source_url"] or ""),
            }


class Neo4jImporter:
    def __init__(self, driver: Any, *, database: str, batch_size: int) -> None:
        self.driver = driver
        self.database = database
        self.batch_size = batch_size

    def prepare_schema(self) -> None:
        queries = (
            "CREATE CONSTRAINT legal_entity_id IF NOT EXISTS "
            "FOR (n:LegalEntity) REQUIRE n.entity_id IS UNIQUE",
            "CREATE CONSTRAINT novinlaw_entity_id IF NOT EXISTS "
            "FOR (n:NovinLawNode) REQUIRE n.entity_id IS UNIQUE",
            "CREATE INDEX novinlaw_node_type IF NOT EXISTS "
            "FOR (n:NovinLawNode) ON (n.node_type)",
            "CREATE INDEX novinlaw_decision_number IF NOT EXISTS "
            "FOR (n:UnanimityDecision) ON (n.decision_number)",
        )
        with self.driver.session(database=self.database) as session:
            for query in queries:
                session.run(query).consume()

    def import_dataset(self, dataset: Dataset) -> tuple[int, int]:
        node_count = 0
        relation_count = 0
        for batch in chunks(iter_nodes(dataset), self.batch_size):
            self._upsert_nodes(batch)
            node_count += len(batch)
            if node_count % (self.batch_size * 10) == 0:
                logging.info("%s: imported %d nodes", dataset.name, node_count)

        for batch in chunks(iter_relations(dataset), self.batch_size):
            self._upsert_relations(batch)
            relation_count += len(batch)
            if relation_count % (self.batch_size * 10) == 0:
                logging.info("%s: imported %d relations", dataset.name, relation_count)
        return node_count, relation_count

    def _upsert_nodes(self, rows: Sequence[dict[str, Any]]) -> None:
        base_rows = [
            {
                "id": row["id"],
                "dataset": row["dataset"],
                "node_type": row["node_type"],
                **row["properties"],
            }
            for row in rows
        ]
        query = """
        UNWIND $rows AS row
        MERGE (node:LegalEntity {entity_id: row.id})
        SET node:NovinLawNode,
            node.node_id = row.id,
            node.source_datasets = CASE
                WHEN row.dataset IN coalesce(node.source_datasets, [])
                THEN node.source_datasets
                ELSE coalesce(node.source_datasets, []) + row.dataset
            END,
            node.node_type = CASE
                WHEN row.dataset = 'laws' THEN row.node_type
                ELSE coalesce(node.node_type, row.node_type)
            END,
            node.subtype = coalesce(row.subtype, node.subtype),
            node.numeric_id = coalesce(row.numeric_id, node.numeric_id),
            node.title = coalesce(row.title, node.title),
            node.url = coalesce(row.url, node.url),
            node.category = coalesce(row.category, node.category),
            node.approval_info = coalesce(row.approval_info, node.approval_info),
            node.year = coalesce(row.year, node.year),
            node.decision_number = coalesce(row.decision_number, node.decision_number),
            node.approval_date = coalesce(row.approval_date, node.approval_date),
            node.subject = coalesce(row.subject, node.subject),
            node.issuing_body = coalesce(row.issuing_body, node.issuing_body),
            node.text = coalesce(row.text, node.text),
            node.access_status = coalesce(row.access_status, node.access_status),
            node.content_hash = coalesce(row.content_hash, node.content_hash),
            node.fetched_at = coalesce(row.fetched_at, node.fetched_at),
            node.metadata_json = coalesce(row.metadata_json, node.metadata_json)
        """
        with self.driver.session(database=self.database) as session:
            session.run(query, rows=base_rows).consume()

            grouped: dict[str, list[str]] = {}
            for row in rows:
                labels = (*TYPE_LABELS[row["dataset"]][row["node_type"]], DATASET_LABELS[row["dataset"]])
                for label in labels:
                    if not LABEL_RE.fullmatch(label):
                        raise ValueError(f"Unsafe Neo4j label: {label}")
                    grouped.setdefault(label, []).append(row["id"])
            for label, entity_ids in grouped.items():
                session.run(
                    f"MATCH (node:NovinLawNode) WHERE node.entity_id IN $ids SET node:{label}",
                    ids=entity_ids,
                ).consume()

    def _upsert_relations(self, rows: Sequence[dict[str, Any]]) -> None:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            relation_type = row["relation_type"]
            if not RELATION_TYPE_RE.fullmatch(relation_type):
                raise ValueError(f"Unsafe Neo4j relation type: {relation_type}")
            grouped.setdefault(relation_type, []).append(row)

        with self.driver.session(database=self.database) as session:
            for relation_type, typed_rows in grouped.items():
                session.run(
                    f"""
                    UNWIND $rows AS row
                    MATCH (source:NovinLawNode {{entity_id: row.source_id}})
                    MATCH (target:NovinLawNode {{entity_id: row.target_id}})
                    MERGE (source)-[edge:{relation_type} {{relation_key: row.relation_key}}]->(target)
                    SET edge.source_datasets = CASE
                            WHEN row.dataset IN coalesce(edge.source_datasets, [])
                            THEN edge.source_datasets
                            ELSE coalesce(edge.source_datasets, []) + row.dataset
                        END,
                        edge.raw_reference = row.raw_reference,
                        edge.confidence = row.confidence,
                        edge.source_url = row.source_url
                    """,
                    rows=typed_rows,
                ).consume()

    def counts(self) -> dict[str, int]:
        with self.driver.session(database=self.database) as session:
            node_count = session.run(
                "MATCH (n:NovinLawNode) RETURN count(n) AS count"
            ).single()["count"]
            relation_count = session.run(
                "MATCH (:NovinLawNode)-[r]->(:NovinLawNode) "
                "WHERE r.relation_key IS NOT NULL RETURN count(r) AS count"
            ).single()["count"]
        return {"nodes": int(node_count), "relations": int(relation_count)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import NovinLaw laws and unanimity SQLite graphs into Neo4j."
    )
    parser.add_argument("laws", type=Path, help="novinlaw_output directory or SQLite file")
    parser.add_argument(
        "unanimity", type=Path, help="novinlaw_unanimity_output directory or SQLite file"
    )
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--username", default=os.environ.get("NEO4J_USERNAME", "neo4j"))
    parser.add_argument("--database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    parser.add_argument(
        "--password-env",
        default="NEO4J_PASSWORD",
        help="Environment variable containing the Neo4j password (default: NEO4J_PASSWORD)",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and count both SQLite graphs without connecting to Neo4j",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s | %(message)s")
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be greater than zero")

    datasets = (
        Dataset("laws", resolve_database(args.laws, "laws")),
        Dataset("unanimity", resolve_database(args.unanimity, "unanimity")),
    )
    totals = Counter()
    for dataset in datasets:
        stats = validate_database(dataset)
        totals["nodes"] += stats.nodes
        totals["relations"] += stats.relations
        logging.info(
            "%s validated: %d nodes, %d relations",
            dataset.name,
            stats.nodes,
            stats.relations,
        )
    if args.dry_run:
        logging.info(
            "Dry run complete: %d source nodes, %d source relations",
            totals["nodes"],
            totals["relations"],
        )
        return 0

    password = os.environ.get(args.password_env)
    if not password:
        raise RuntimeError(
            f"Neo4j password is missing; set environment variable {args.password_env}"
        )

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(args.uri, auth=(args.username, password))
    try:
        driver.verify_connectivity()
        importer = Neo4jImporter(driver, database=args.database, batch_size=args.batch_size)
        importer.prepare_schema()
        for dataset in datasets:
            imported_nodes, imported_relations = importer.import_dataset(dataset)
            logging.info(
                "%s complete: %d nodes, %d relations",
                dataset.name,
                imported_nodes,
                imported_relations,
            )
        counts = importer.counts()
        logging.info(
            "Neo4j NovinLaw graph: %d unique nodes, %d unique keyed relations",
            counts["nodes"],
            counts["relations"],
        )
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        logging.error("Import failed: %s", exc)
        sys.exit(1)
