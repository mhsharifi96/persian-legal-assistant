from __future__ import annotations

from legal_assistant.application.document_ingestion import DocumentSource
from legal_assistant.infrastructure.documents.models import LegalFile


class DjangoDocumentRepository:
    def upsert(self, document: DocumentSource) -> None:
        LegalFile.objects.update_or_create(
            id=document.id,
            defaults={
                "title": document.title,
                "file_url": document.file_url,
                "local_address_file": document.local_address_file,
            },
        )

    def mark_indexed(self, document_id: str, point_count: int) -> None:
        LegalFile.objects.filter(id=document_id).update(
            ingestion_status=LegalFile.IngestionStatus.INDEXED,
            qdrant_points=point_count,
            ingestion_error="",
        )

    def mark_failed(self, document_id: str, error: str) -> None:
        LegalFile.objects.filter(id=document_id).update(
            ingestion_status=LegalFile.IngestionStatus.FAILED,
            qdrant_points=0,
            ingestion_error=error,
        )
