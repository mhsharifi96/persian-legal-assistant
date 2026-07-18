from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from legal_assistant.domain.models import LegalDocument


class DadrahJsonlParser:
    """Parse the nested Dadrah consultation export into source documents."""

    def __init__(self, *, jurisdiction: str = "IR", max_records: int | None = None) -> None:
        self._jurisdiction = jurisdiction
        self._max_records = max_records

    def parse(self, source_uri: str) -> list[LegalDocument]:
        path = Path(source_uri).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Dadrah JSONL source does not exist: {path}")
        if path.suffix.casefold() != ".jsonl":
            raise ValueError(f"Dadrah parser requires a .jsonl file: {path}")

        documents: list[LegalDocument] = []
        with path.open("r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, start=1):
                if self._max_records is not None and len(documents) >= self._max_records:
                    break
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError(f"Dadrah record {line_number} must be an object: {path}")
                question = record.get("question")
                if record.get("status") == "not_found" or not isinstance(question, dict):
                    continue

                request_id = str(record.get("request_id") or "").strip()
                if not request_id:
                    raise ValueError(f"Dadrah record {line_number} has no request_id: {path}")
                title = str(question.get("title") or f"مشاوره حقوقی {request_id}").strip()
                question_text = str(question.get("text") or "").strip()
                if not question_text and not title:
                    continue
                page_url = str(record.get("page_url") or path.as_uri())
                tags = self._objects(record=question.get("tags"))
                answers = self._objects(record=record.get("answers"))
                documents.append(
                    LegalDocument(
                        id=f"dadrah:{request_id}",
                        title=title,
                        source_uri=page_url,
                        jurisdiction=self._jurisdiction,
                        document_type="legal_consultation",
                        text=question_text,
                        parser_name="dadrah_jsonl",
                        metadata={
                            "source_name": "dadrah",
                            "source_format": "jsonl",
                            "request_id": request_id,
                            "fetched_at": record.get("fetched_at"),
                            "page_url": page_url,
                            "source_file": path.name,
                            "source_line": line_number,
                            "tags": tags,
                            "_transient_answers": answers,
                            "trust_tier": "public_user_generated_consultation",
                        },
                    )
                )
        return documents

    @staticmethod
    def _objects(record: Any) -> list[dict[str, Any]]:
        if not isinstance(record, list):
            return []
        return [dict(item) for item in record if isinstance(item, dict)]
