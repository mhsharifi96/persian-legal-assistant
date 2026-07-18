from __future__ import annotations

from django.contrib import admin

from legal_assistant.infrastructure.orm.models import (
    EvaluationRecordRow,
    LawyerRow,
    LegalChunkRow,
    LegalDocumentRow,
)


@admin.register(LawyerRow)
class LawyerAdmin(admin.ModelAdmin):
    list_display = ("full_name", "external_id", "location", "success_rate")
    list_filter = ("location",)
    search_fields = ("full_name", "external_id", "location")
    ordering = ("full_name",)


@admin.register(LegalDocumentRow)
class LegalDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "external_id",
        "jurisdiction",
        "document_type",
        "version",
    )
    list_filter = ("jurisdiction", "document_type")
    search_fields = ("title", "external_id", "source_uri")
    ordering = ("title",)


@admin.register(LegalChunkRow)
class LegalChunkAdmin(admin.ModelAdmin):
    list_display = (
        "external_id",
        "document",
        "source_format",
        "structure_label",
    )
    search_fields = ("external_id", "text", "metadata")
    raw_id_fields = ("document",)

    @admin.display(description="Source format")
    def source_format(self, obj: LegalChunkRow) -> str:
        return str((obj.metadata or {}).get("source_format", ""))

    @admin.display(description="Structure")
    def structure_label(self, obj: LegalChunkRow) -> str:
        metadata = obj.metadata or {}
        hierarchy = metadata.get("hierarchy") or metadata
        article = hierarchy.get("article_number")
        note = hierarchy.get("note_number")
        if article and note:
            return f"ماده {article}، تبصره {note}"
        if article:
            return f"ماده {article}"
        return str(metadata.get("sheet_name") or metadata.get("record_index") or "")


@admin.register(EvaluationRecordRow)
class EvaluationRecordAdmin(admin.ModelAdmin):
    list_display = ("question", "created_at")
    search_fields = ("question", "answer", "ground_truth")
    date_hierarchy = "created_at"
