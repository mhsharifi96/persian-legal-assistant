from __future__ import annotations

from django.contrib import admin, messages
from django.http import HttpRequest
from django.db.models import QuerySet

from legal_assistant.application.document_ingestion import DocumentSource
from legal_assistant.infrastructure.documents.factory import (
    build_document_ingestion_service,
)
from legal_assistant.infrastructure.documents.models import LegalFile


@admin.register(LegalFile)
class LegalFileAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "ingestion_status", "qdrant_points", "updated_at")
    list_filter = ("ingestion_status",)
    search_fields = ("id", "title", "file_url", "local_address_file")
    readonly_fields = ("ingestion_status", "qdrant_points", "ingestion_error")
    actions = ("ingest_selected",)

    @admin.action(description="استخراج PDF و درج embedding در Qdrant")
    def ingest_selected(
        self, request: HttpRequest, queryset: QuerySet[LegalFile]
    ) -> None:
        service = build_document_ingestion_service()
        succeeded = 0
        failed = 0
        for row in queryset:
            try:
                service.ingest(
                    DocumentSource(
                        id=row.id,
                        title=row.title,
                        file_url=row.file_url,
                        local_address_file=row.local_address_file,
                    )
                )
                succeeded += 1
            except Exception:
                failed += 1
        self.message_user(
            request,
            f"{succeeded} فایل نمایه‌سازی شد؛ {failed} فایل ناموفق بود.",
            level=messages.SUCCESS if failed == 0 else messages.WARNING,
        )
