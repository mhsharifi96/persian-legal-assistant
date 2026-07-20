from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from legal_assistant.infrastructure.documents.factory import (
    build_document_ingestion_service,
)
from legal_assistant.infrastructure.documents.manifest import iter_pdf_documents


class Command(BaseCommand):
    help = "Upsert local PDF records into Django and idempotently index them in Qdrant."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "manifest",
            nargs="?",
            default="novinlaw_files_output/files.jsonl",
        )
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args: Any, **options: Any) -> None:
        manifest = Path(options["manifest"]).resolve()
        if not manifest.is_file():
            raise CommandError(f"Manifest not found: {manifest}")
        limit = options["limit"]
        if limit is not None and limit <= 0:
            raise CommandError("--limit must be greater than zero")

        service = build_document_ingestion_service()
        documents = 0
        points = 0
        for document in iter_pdf_documents(manifest):
            if limit is not None and documents >= limit:
                break
            try:
                point_count = service.ingest(document)
            except Exception as exc:
                raise CommandError(f"Failed to ingest {document.id}: {exc}") from exc
            documents += 1
            points += point_count
            self.stdout.write(f"Indexed {document.id}: {point_count} point(s)")
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported/indexed {documents} PDF file(s) with {points} Qdrant point(s)."
            )
        )
