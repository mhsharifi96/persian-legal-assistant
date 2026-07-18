from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.strip().casefold().encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{digest}"


@dataclass(frozen=True)
class DadrahGraphStats:
    questions: int = 0
    answers: int = 0
    tag_links: int = 0
    lawyer_links: int = 0

    def __add__(self, other: DadrahGraphStats) -> DadrahGraphStats:
        return DadrahGraphStats(
            questions=self.questions + other.questions,
            answers=self.answers + other.answers,
            tag_links=self.tag_links + other.tag_links,
            lawyer_links=self.lawyer_links + other.lawyer_links,
        )


class DadrahNativeGraphImporter:
    """Stream Dadrah JSONL into explicit source nodes without LegalChunk nodes."""

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
            "CREATE INDEX dadrah_question_request IF NOT EXISTS "
            "FOR (node:Question) ON (node.request_id)",
            "CREATE INDEX dadrah_answer_request IF NOT EXISTS "
            "FOR (node:Answer) ON (node.request_id)",
        )
        with self._driver.session(database=self._database) as session:
            for query in queries:
                session.run(query).consume()

    def import_files(
        self, paths: Sequence[Path], *, limit: int | None = None
    ) -> DadrahGraphStats:
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        self.prepare_schema()
        total = DadrahGraphStats()
        batch: list[dict[str, Any]] = []
        remaining = limit
        for path in paths:
            with path.open("r", encoding="utf-8-sig") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if remaining is not None and remaining <= 0:
                        break
                    if not line.strip():
                        continue
                    transformed = self.transform_record(
                        json.loads(line), source_file=path.name, source_line=line_number
                    )
                    if transformed is None:
                        continue
                    batch.append(transformed)
                    if remaining is not None:
                        remaining -= 1
                    if len(batch) >= self._batch_size:
                        total += self._write_batch(batch)
                        batch.clear()
            if remaining is not None and remaining <= 0:
                break
        if batch:
            total += self._write_batch(batch)
        return total

    @staticmethod
    def transform_record(
        record: Any, *, source_file: str, source_line: int
    ) -> dict[str, Any] | None:
        if not isinstance(record, dict) or record.get("status") == "not_found":
            return None
        question = record.get("question")
        if not isinstance(question, dict):
            return None
        request_id = str(record.get("request_id") or "").strip()
        if not request_id:
            raise ValueError(f"Dadrah record {source_file}:{source_line} has no request_id")

        question_id = f"question:{request_id}"
        tags: list[dict[str, str]] = []
        for tag in question.get("tags") or ():
            if not isinstance(tag, dict):
                continue
            name = str(tag.get("name") or "").strip()
            if not name:
                continue
            tags.append(
                {
                    "id": stable_id("tag", name),
                    "name": name,
                    "url": str(tag.get("url") or "").strip(),
                }
            )

        answers: list[dict[str, Any]] = []
        for position, answer in enumerate(record.get("answers") or (), start=1):
            if not isinstance(answer, dict):
                continue
            text = str(answer.get("text") or "").strip()
            if not text:
                continue
            lawyer = answer.get("lawyer") if isinstance(answer.get("lawyer"), dict) else {}
            lawyer_name = str(lawyer.get("name") or "").strip()
            profile_url = str(lawyer.get("profile_url") or "").strip()
            answers.append(
                {
                    "id": f"answer:{request_id}:{position}",
                    "request_id": request_id,
                    "position": position,
                    "answer_number": str(answer.get("number") or position),
                    "text": text,
                    "date": answer.get("date"),
                    "time": answer.get("time"),
                    "lawyer": (
                        {
                            "id": stable_id("lawyer", profile_url or lawyer_name),
                            "name": lawyer_name,
                            "city": lawyer.get("city"),
                            "profile_url": profile_url,
                        }
                        if lawyer_name
                        else None
                    ),
                }
            )

        return {
            "question": {
                "id": question_id,
                "request_id": request_id,
                "title": str(question.get("title") or f"مشاوره حقوقی {request_id}").strip(),
                "text": str(question.get("text") or "").strip(),
                "page_url": str(record.get("page_url") or "").strip(),
                "fetched_at": record.get("fetched_at"),
                "source_file": source_file,
                "source_line": source_line,
                "trust_tier": "public_user_generated_consultation",
            },
            "tags": tags,
            "answers": answers,
        }

    def _write_batch(self, records: Sequence[dict[str, Any]]) -> DadrahGraphStats:
        questions = [record["question"] for record in records]
        tags_by_id: dict[str, dict[str, Any]] = {}
        lawyers_by_id: dict[str, dict[str, Any]] = {}
        answers: list[dict[str, Any]] = []
        tag_links: list[dict[str, str]] = []
        answer_links: list[dict[str, str]] = []
        lawyer_links: list[dict[str, str]] = []
        for record in records:
            question_id = record["question"]["id"]
            for tag in record["tags"]:
                tags_by_id[tag["id"]] = tag
                tag_links.append({"question_id": question_id, "tag_id": tag["id"]})
            for answer in record["answers"]:
                answers.append({key: value for key, value in answer.items() if key != "lawyer"})
                answer_links.append({"question_id": question_id, "answer_id": answer["id"]})
                if answer["lawyer"]:
                    lawyer = answer["lawyer"]
                    lawyers_by_id[lawyer["id"]] = lawyer
                    lawyer_links.append(
                        {"answer_id": answer["id"], "lawyer_id": lawyer["id"]}
                    )

        with self._driver.session(database=self._database) as session:
            session.run(
                """
                UNWIND $rows AS row
                MERGE (node:LegalEntity {entity_id: row.id})
                SET node:DadrahNode:Question,
                    node.type='Question', node.name=row.title,
                    node.request_id=row.request_id, node.title=row.title,
                    node.text=row.text, node.page_url=row.page_url,
                    node.fetched_at=row.fetched_at, node.source_file=row.source_file,
                    node.source_line=row.source_line, node.trust_tier=row.trust_tier
                """,
                rows=questions,
            ).consume()
            session.run(
                """
                UNWIND $rows AS row
                MERGE (node:LegalEntity {entity_id: row.id})
                SET node:DadrahNode:Tag, node.type='Tag', node.name=row.name,
                    node.url=CASE WHEN row.url<>'' THEN row.url ELSE node.url END
                """,
                rows=list(tags_by_id.values()),
            ).consume()
            session.run(
                """
                UNWIND $rows AS row
                MERGE (node:LegalEntity {entity_id: row.id})
                SET node:DadrahNode:Answer, node.type='Answer',
                    node.name='پاسخ ' + row.answer_number,
                    node.request_id=row.request_id, node.position=row.position,
                    node.answer_number=row.answer_number, node.text=row.text,
                    node.date=row.date, node.time=row.time
                """,
                rows=answers,
            ).consume()
            session.run(
                """
                UNWIND $rows AS row
                MERGE (node:LegalEntity {entity_id: row.id})
                SET node:DadrahNode:Lawyer, node.type='Lawyer', node.name=row.name,
                    node.city=coalesce(row.city,node.city),
                    node.profile_url=CASE WHEN row.profile_url<>'' THEN row.profile_url ELSE node.profile_url END
                """,
                rows=list(lawyers_by_id.values()),
            ).consume()
            self._write_links(session, "TAGGED_WITH", tag_links, "question_id", "tag_id")
            self._write_links(session, "HAS_ANSWER", answer_links, "question_id", "answer_id")
            self._write_links(session, "ANSWERED_BY", lawyer_links, "answer_id", "lawyer_id")

        return DadrahGraphStats(
            questions=len(questions),
            answers=len(answers),
            tag_links=len(tag_links),
            lawyer_links=len(lawyer_links),
        )

    @staticmethod
    def _write_links(
        session: Any,
        relation_type: str,
        rows: Sequence[dict[str, str]],
        source_key: str,
        target_key: str,
    ) -> None:
        if not rows:
            return
        session.run(
            f"""
            UNWIND $rows AS row
            MATCH (source:DadrahNode {{entity_id: row.{source_key}}})
            MATCH (target:DadrahNode {{entity_id: row.{target_key}}})
            MERGE (source)-[:{relation_type}]->(target)
            """,
            rows=list(rows),
        ).consume()

    def cleanup_legacy_graph(self) -> dict[str, int]:
        with self._driver.session(database=self._database) as session:
            chunk_count = session.run(
                "MATCH (chunk:LegalChunk) WHERE chunk.chunk_id STARTS WITH 'dadrah:' "
                "RETURN count(chunk) AS count"
            ).single()["count"]
            consultation_count = session.run(
                "MATCH (node:LegalEntity) WHERE node.type='Consultation' "
                "RETURN count(node) AS count"
            ).single()["count"]
            session.run(
                """
                MATCH (chunk:LegalChunk)
                WHERE chunk.chunk_id STARTS WITH 'dadrah:'
                CALL (chunk) { DETACH DELETE chunk } IN TRANSACTIONS OF 5000 ROWS
                """
            ).consume()
            session.run(
                """
                MATCH (node:LegalEntity) WHERE node.type='Consultation'
                CALL (node) { DETACH DELETE node } IN TRANSACTIONS OF 5000 ROWS
                """
            ).consume()
        return {
            "legacy_chunks_deleted": int(chunk_count),
            "legacy_consultations_deleted": int(consultation_count),
        }

    def counts(self) -> dict[str, int]:
        output: dict[str, int] = {}
        with self._driver.session(database=self._database) as session:
            for label in ("Question", "Answer", "Lawyer", "Tag"):
                output[label.lower()] = int(
                    session.run(f"MATCH (node:DadrahNode:{label}) RETURN count(node) AS count")
                    .single()["count"]
                )
            output["relationships"] = int(
                session.run(
                    "MATCH (:DadrahNode)-[edge]->(:DadrahNode) RETURN count(edge) AS count"
                ).single()["count"]
            )
        return output
