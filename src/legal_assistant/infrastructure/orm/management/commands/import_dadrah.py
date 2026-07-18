from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from django.conf import settings as django_settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from legal_assistant.application.services.ingestion import DocumentIngestionService
from legal_assistant.config.bootstrap import (
    build_document_store,
    build_embedding_model,
    build_vector_store,
)
from legal_assistant.infrastructure.chunkers import DadrahConsultationChunker
from legal_assistant.infrastructure.graphstores.dadrah_native import (
    DadrahNativeGraphImporter,
)
from legal_assistant.infrastructure.parsers import DadrahJsonlParser


class Command(BaseCommand):
    help = "Import Dadrah consultation JSONL into ORM, optionally Qdrant and Neo4j."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("source", type=Path)
        parser.add_argument(
            "--qdrant",
            action="store_true",
            help="Embed and index question/answer chunks in Qdrant.",
        )
        parser.add_argument(
            "--neo4j",
            action="store_true",
            help="Create deterministic Question/Answer/Lawyer/Tag nodes in Neo4j.",
        )
        parser.add_argument(
            "--neo4j-only",
            action="store_true",
            help=(
                "Import only into Neo4j without persisting consultations/chunks "
                "to the Django document store; requires --neo4j."
            ),
        )
        parser.add_argument(
            "--collection",
            default="dadrah_consultations",
            help="Qdrant collection name (default: dadrah_consultations).",
        )
        parser.add_argument(
            "--include-answers-in-qdrant",
            action="store_true",
            help="Also embed unverified lawyer answers; default indexes questions only.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Import at most this many valid consultations, useful for a trial run.",
        )
        parser.add_argument(
            "--allow-external-processing",
            action="store_true",
            help="Acknowledge sending public user-generated text to an external embedding provider.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source = Path(options["source"]).expanduser().resolve()
        files = list(self._jsonl_files(source))
        if not files:
            raise CommandError(f"No Dadrah JSONL files found under {source}")

        limit = options["limit"]
        if limit is not None and limit <= 0:
            raise CommandError("--limit must be greater than zero")
        if options["neo4j_only"] and not options["neo4j"]:
            raise CommandError("--neo4j-only requires --neo4j")

        app_settings = replace(
            django_settings.LEGAL_ASSISTANT_SETTINGS,
            document_store_provider="orm",
            qdrant_collection_name=str(options["collection"]),
        )
        document_store = (
            None
            if options["neo4j_only"]
            else build_document_store(app_settings)
        )

        embeddings = None
        vector_store = None
        if options["qdrant"]:
            if app_settings.vectorstore_provider != "qdrant":
                raise CommandError("Set VECTORSTORE_PROVIDER=qdrant before using --qdrant.")
            if app_settings.embedding_provider == "fake":
                raise CommandError("Configure a real EMBEDDING_PROVIDER before using --qdrant.")
            if (
                app_settings.embedding_provider == "openai"
                and not options["allow_external_processing"]
            ):
                raise CommandError(
                    "OpenAI embeddings send consultation text to an external provider. "
                    "Review your data policy, then pass --allow-external-processing."
                )
            embeddings = build_embedding_model(app_settings)
            vector_store = build_vector_store(app_settings)

        native_graph_entities = 0
        native_graph_relations = 0
        if options["neo4j"]:
            if app_settings.graphstore_provider != "neo4j":
                raise CommandError("Set GRAPHSTORE_PROVIDER=neo4j before using --neo4j.")
            importer = DadrahNativeGraphImporter(
                uri=app_settings.neo4j_uri,
                username=app_settings.neo4j_username,
                password=app_settings.neo4j_password,
                database=app_settings.neo4j_database,
            )
            try:
                graph_stats = importer.import_files(files, limit=limit)
            finally:
                importer.close()
            native_graph_entities = graph_stats.questions + graph_stats.answers
            native_graph_relations = (
                graph_stats.answers + graph_stats.tag_links + graph_stats.lawyer_links
            )
            if options["neo4j_only"]:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Imported {graph_stats.questions} questions and "
                        f"{graph_stats.answers} answers into Neo4j; "
                        f"graph relations={native_graph_relations}."
                    )
                )
                return

        remaining = limit
        document_count = 0
        chunk_count = 0
        graph_entity_count = native_graph_entities
        graph_relation_count = native_graph_relations
        error_count = 0
        for path in files:
            if remaining is not None and remaining <= 0:
                break
            parser = DadrahJsonlParser(
                jurisdiction=app_settings.jurisdiction,
                max_records=remaining,
            )
            service = DocumentIngestionService(
                parser=parser,
                chunker=DadrahConsultationChunker(
                    max_chunk_tokens=app_settings.max_chunk_tokens,
                    chunk_overlap_tokens=app_settings.chunk_overlap_tokens,
                ),
                document_store=document_store,
                embeddings=embeddings,
                vector_store=vector_store,
                embedding_batch_size=app_settings.embedding_batch_size,
                vector_chunk_filter=(
                    None
                    if options["include_answers_in_qdrant"]
                    else lambda chunk: chunk.metadata.get("content_role") == "question"
                ),
            )
            result = service.ingest(str(path))
            document_count += result.document_count
            chunk_count += result.chunk_count
            graph_entity_count += result.graph_entity_count
            graph_relation_count += result.graph_relation_count
            error_count += len(result.errors)
            if remaining is not None:
                remaining -= result.document_count
            self.stdout.write(
                f"{path.name}: {result.document_count} consultations, "
                f"{result.chunk_count} chunks, {len(result.errors)} errors"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {document_count} consultations and {chunk_count} chunks; "
                f"graph entities={graph_entity_count}, graph relations={graph_relation_count}, "
                f"errors={error_count}."
            )
        )

    @staticmethod
    def _jsonl_files(source: Path) -> Iterable[Path]:
        if source.is_file() and source.suffix.casefold() == ".jsonl":
            yield source
            return
        if source.is_dir():
            yield from sorted(source.glob("*.jsonl"))
            return
        raise CommandError(f"Dadrah source does not exist or is not JSONL: {source}")
