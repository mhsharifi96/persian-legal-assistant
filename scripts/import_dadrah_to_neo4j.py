#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from legal_assistant.infrastructure.graphstores.dadrah_native import (  # noqa: E402
    DadrahNativeGraphImporter,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import Dadrah as Question/Answer/Lawyer/Tag nodes without LegalChunk."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--username", default=os.environ.get("NEO4J_USERNAME", "neo4j"))
    parser.add_argument("--database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--password-env", default="NEO4J_PASSWORD")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--cleanup-legacy", action="store_true")
    args = parser.parse_args()

    paths = (
        [args.source.resolve()]
        if args.source.is_file()
        else sorted(args.source.resolve().glob("*.jsonl"))
    )
    if not paths:
        raise FileNotFoundError(f"No Dadrah JSONL files found under {args.source}")
    password = os.environ.get(args.password_env)
    if not password:
        raise RuntimeError(f"Set {args.password_env} before connecting to Neo4j")

    importer = DadrahNativeGraphImporter(
        uri=args.uri,
        username=args.username,
        password=password,
        database=args.database,
        batch_size=args.batch_size,
    )
    try:
        stats = importer.import_files(paths, limit=args.limit)
        logging.warning(
            "Imported questions=%d answers=%d tag_links=%d lawyer_links=%d",
            stats.questions, stats.answers, stats.tag_links, stats.lawyer_links,
        )
        if args.cleanup_legacy:
            logging.warning("Legacy cleanup: %s", importer.cleanup_legacy_graph())
        logging.warning("Dadrah graph: %s", importer.counts())
    finally:
        importer.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        logging.error("Dadrah import failed: %s", exc)
        sys.exit(1)
