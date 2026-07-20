from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from legal_assistant.application.document_ingestion import DocumentSource


def iter_pdf_documents(manifest: Path) -> Iterator[DocumentSource]:
    metadata = _load_companion_metadata(manifest)
    with manifest.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Expected JSON object at {manifest}:{line_number}")
            enriched = metadata.get(str(row.get("file_url") or ""), row)
            if str(enriched.get("type_file") or "").casefold() != "pdf":
                continue
            local_path = _resolve_local_path(manifest, enriched.get("local_path"))
            if local_path is None or not local_path.is_file():
                continue
            title = str(enriched.get("title") or "").strip()
            file_url = str(enriched.get("file_url") or "").strip() or None
            raw_id = str(enriched.get("id") or "").strip()
            if not raw_id:
                identity = file_url or f"{title}:{local_path}"
                raw_id = f"legal_file:{hashlib.sha256(identity.encode()).hexdigest()[:24]}"
            yield DocumentSource(
                id=raw_id,
                title=title,
                file_url=file_url,
                local_address_file=str(local_path.resolve()),
            )


def _load_companion_metadata(manifest: Path) -> dict[str, dict[str, Any]]:
    companion = manifest.with_name("files_metadata.jsonl")
    if manifest.name == "files_metadata.jsonl" or not companion.is_file():
        return {}
    output: dict[str, dict[str, Any]] = {}
    with companion.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict) and row.get("file_url"):
                output[str(row["file_url"])] = row
    return output


def _resolve_local_path(manifest: Path, value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else manifest.parent / path
