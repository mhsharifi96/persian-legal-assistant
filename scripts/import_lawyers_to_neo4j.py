#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from legal_assistant.infrastructure.graphstores.dadrah_lawyers import (  # noqa: E402
    DadrahLawyerGraphImporter,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Idempotently import Dadrah lawyer JSONL into Neo4j Lawyer nodes."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--username", default=os.environ.get("NEO4J_USERNAME", "neo4j"))
    parser.add_argument("--database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--password-env", default="NEO4J_PASSWORD")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    if not args.source.is_file():
        raise FileNotFoundError(f"Lawyer JSONL not found: {args.source}")
    password = os.environ.get(args.password_env)
    if not password:
        raise RuntimeError(f"Set {args.password_env} before connecting to Neo4j")

    importer = DadrahLawyerGraphImporter(
        uri=args.uri,
        username=args.username,
        password=password,
        database=args.database,
        batch_size=args.batch_size,
    )
    try:
        stats = importer.import_file(args.source.resolve())
        logging.warning(
            "Imported source_rows=%d; graph lawyer_nodes=%d; imported_lawyer_ids=%d",
            stats.source_rows,
            stats.lawyer_nodes,
            stats.imported_lawyer_ids,
        )
    finally:
        importer.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        logging.error("Lawyer import failed: %s", exc)
        sys.exit(1)
