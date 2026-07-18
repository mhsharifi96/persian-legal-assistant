from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "import_novinlaw_to_neo4j.py"
SPEC = importlib.util.spec_from_file_location("novinlaw_neo4j_import", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _make_laws_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE nodes (
                id TEXT PRIMARY KEY, type TEXT NOT NULL, subtype TEXT,
                numeric_id TEXT, title TEXT, url TEXT, category TEXT,
                approval_info TEXT, text TEXT, content_hash TEXT, fetched_at TEXT
            );
            CREATE TABLE relations (
                source_id TEXT, target_id TEXT, relation_type TEXT,
                raw_reference TEXT, confidence REAL, source_url TEXT
            );
            INSERT INTO nodes VALUES
                ('document:1','document',NULL,'1','قانون آزمون','https://example/law',NULL,NULL,'متن','h1','now'),
                ('article:1','article','ماده','1','ماده ۱','https://example/article',NULL,NULL,'ماده','h2','now');
            INSERT INTO relations VALUES
                ('document:1','article:1','CONTAINS','',1.0,'https://example/law');
            """
        )


def test_validate_and_iterate_laws_database(tmp_path: Path) -> None:
    db = tmp_path / "novinlaw.sqlite3"
    _make_laws_db(db)
    dataset = MODULE.Dataset("laws", db)

    stats = MODULE.validate_database(dataset)
    nodes = list(MODULE.iter_nodes(dataset))
    relations = list(MODULE.iter_relations(dataset))

    assert stats.nodes == 2
    assert stats.relations == 1
    assert nodes[0]["dataset"] == "laws"
    assert {node["node_type"] for node in nodes} == {"document", "article"}
    assert relations[0]["relation_type"] == "CONTAINS"
    assert len(relations[0]["relation_key"]) == 64


def test_slug_independent_relation_key_is_deterministic() -> None:
    first = MODULE.relation_key("a", "b", "REFERENCES", "ماده ۱")
    second = MODULE.relation_key("a", "b", "REFERENCES", "ماده ۱")
    different = MODULE.relation_key("a", "b", "REFERENCES", "ماده ۲")

    assert first == second
    assert first != different


def test_resolve_database_accepts_output_directory(tmp_path: Path) -> None:
    db = tmp_path / "novinlaw.sqlite3"
    _make_laws_db(db)

    assert MODULE.resolve_database(tmp_path, "laws") == db.resolve()
