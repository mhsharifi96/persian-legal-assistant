from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from django.conf import settings as django_settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from legal_assistant.config.bootstrap import build_document_parser, build_document_store
from legal_assistant.infrastructure.chunkers import PersianLegalHierarchicalChunker
from legal_assistant.infrastructure.parsers.local_file import LocalFileDocumentParser


class Command(BaseCommand):
    help = "Import PDF, Word, Excel, or JSONL documents into the legal document store."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("sources", nargs="+", type=Path)
        parser.add_argument(
            "--parser",
            default="local",
            help="Configured parser provider (default: local)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        app_settings = replace(
            django_settings.LEGAL_ASSISTANT_SETTINGS,
            parser_provider=str(options["parser"]),
            document_store_provider="orm",
        )
        document_parser = build_document_parser(app_settings)
        document_store = build_document_store(app_settings)
        chunker = PersianLegalHierarchicalChunker(
            max_chunk_tokens=app_settings.max_chunk_tokens,
            chunk_overlap_tokens=app_settings.chunk_overlap_tokens,
        )

        paths = list(self._expand_sources(options["sources"]))
        if not paths:
            raise CommandError("No supported documents were found.")

        document_count = 0
        chunk_count = 0
        for path in paths:
            try:
                documents = document_parser.parse(str(path))
            except Exception as exc:
                raise CommandError(f"Could not parse {path}: {exc}") from exc
            for document in documents:
                chunks = chunker.chunk(document)
                document_store.save_document(document, chunks)
                document_count += 1
                chunk_count += len(chunks)

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {document_count} documents and {chunk_count} chunks from {len(paths)} files."
            )
        )

    @staticmethod
    def _expand_sources(sources: Iterable[Path]) -> Iterable[Path]:
        supported = LocalFileDocumentParser.SUPPORTED_EXTENSIONS
        for source in sources:
            path = source.expanduser().resolve()
            if path.is_file():
                if path.suffix.casefold() not in supported:
                    raise CommandError(f"Unsupported document format: {path}")
                yield path
                continue
            if path.is_dir():
                for candidate in sorted(path.rglob("*")):
                    if candidate.is_file() and candidate.suffix.casefold() in supported:
                        yield candidate
                continue
            raise CommandError(f"Document source does not exist: {path}")
