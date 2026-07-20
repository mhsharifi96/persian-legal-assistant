from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

from legal_assistant.infrastructure.graphstores.dadrah_native import stable_id


@dataclass(frozen=True)
class DadrahLawyerImportStats:
    source_rows: int
    lawyer_nodes: int
    imported_lawyer_ids: int


class DadrahLawyerGraphImporter:
    """Idempotently enrich/create Dadrah Lawyer nodes from lawyer JSONL."""

    def __init__(
        self,
        *,
        uri: str,
        username: str,
        password: str,
        database: str = "neo4j",
        batch_size: int = 500,
        driver: Any | None = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        self._driver = driver or GraphDatabase.driver(uri, auth=(username, password))
        self._owns_driver = driver is None
        self._database = database
        self._batch_size = batch_size

    def close(self) -> None:
        if self._owns_driver:
            self._driver.close()

    def prepare_schema(self) -> None:
        queries = (
            "CREATE CONSTRAINT legal_entity_entity_id IF NOT EXISTS "
            "FOR (node:LegalEntity) REQUIRE node.entity_id IS UNIQUE",
            "CREATE CONSTRAINT dadrah_entity_id IF NOT EXISTS "
            "FOR (node:DadrahNode) REQUIRE node.entity_id IS UNIQUE",
            "CREATE CONSTRAINT lawyer_lawyer_id IF NOT EXISTS "
            "FOR (node:Lawyer) REQUIRE node.lawyer_id IS UNIQUE",
        )
        with self._driver.session(database=self._database) as session:
            for query in queries:
                session.run(query).consume()

    def import_file(self, path: Path) -> DadrahLawyerImportStats:
        self.prepare_schema()
        seen_ids: set[str] = set()
        seen_profile_urls: set[str] = set()
        batch: list[dict[str, Any]] = []
        source_rows = 0

        for row in self._iter_rows(path):
            source_rows += 1
            lawyer = self.transform_record(row, source_file=path.name, source_line=source_rows)
            lawyer_id = lawyer["lawyer_id"]
            profile_url = lawyer["profile_url"]
            if lawyer_id in seen_ids:
                raise ValueError(f"Duplicate lawyer_id in {path}: {lawyer_id}")
            if profile_url in seen_profile_urls:
                raise ValueError(f"Duplicate profile_url in {path}: {profile_url}")
            seen_ids.add(lawyer_id)
            seen_profile_urls.add(profile_url)
            batch.append(lawyer)
            if len(batch) >= self._batch_size:
                self._write_batch(batch)
                batch.clear()

        if batch:
            self._write_batch(batch)

        counts = self.counts()
        return DadrahLawyerImportStats(
            source_rows=source_rows,
            lawyer_nodes=counts["lawyer_nodes"],
            imported_lawyer_ids=counts["imported_lawyer_ids"],
        )

    @staticmethod
    def _iter_rows(path: Path) -> Iterator[Any]:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc

    @staticmethod
    def transform_record(
        record: Any, *, source_file: str, source_line: int
    ) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError(f"Expected object at {source_file}:{source_line}")
        lawyer_id = str(record.get("lawyer_id") or "").strip()
        name = str(record.get("name") or "").strip()
        profile_url = str(record.get("profile_url") or "").strip().rstrip("/")
        slug_url = str(record.get("slug_url") or "").strip().rstrip("/")
        if not lawyer_id or not name or not profile_url:
            raise ValueError(
                f"Missing lawyer_id, name, or profile_url at {source_file}:{source_line}"
            )
        specialties = record.get("specialties") or []
        if not isinstance(specialties, list) or not all(
            isinstance(value, str) for value in specialties
        ):
            raise ValueError(f"Invalid specialties at {source_file}:{source_line}")
        return {
            "entity_id": stable_id("lawyer", slug_url or profile_url),
            "lawyer_id": lawyer_id,
            "name": name,
            "listing_name": str(record.get("listing_name") or "").strip(),
            "profile_url": profile_url,
            "slug_url": slug_url,
            "city": str(record.get("city") or "").strip(),
            "email": str(record.get("email") or "").strip(),
            "address": str(record.get("address") or "").strip(),
            "specialties": [value.strip() for value in specialties if value.strip()],
            "source_status": str(record.get("status") or "").strip(),
            "source_updated_at": str(record.get("updated_at") or "").strip(),
        }

    def _write_batch(self, rows: Sequence[dict[str, Any]]) -> None:
        with self._driver.session(database=self._database) as session:
            session.run(
                """
                UNWIND $rows AS row
                MERGE (node:LegalEntity {entity_id: row.entity_id})
                SET node:DadrahNode:Lawyer,
                    node.type = 'Lawyer',
                    node.source = 'dadrah.ir',
                    node.lawyer_id = row.lawyer_id,
                    node.name = row.name,
                    node.listing_name = row.listing_name,
                    node.profile_url = row.profile_url,
                    node.slug_url = row.slug_url,
                    node.city = row.city,
                    node.email = row.email,
                    node.address = row.address,
                    node.specialties = row.specialties,
                    node.source_status = row.source_status,
                    node.source_updated_at = row.source_updated_at
                """,
                rows=list(rows),
            ).consume()

    def counts(self) -> dict[str, int]:
        with self._driver.session(database=self._database) as session:
            row = session.run(
                """
                MATCH (node:Lawyer)
                RETURN count(node) AS lawyer_nodes,
                       count(node.lawyer_id) AS imported_lawyer_ids
                """
            ).single()
        return {
            "lawyer_nodes": int(row["lawyer_nodes"]),
            "imported_lawyer_ids": int(row["imported_lawyer_ids"]),
        }
