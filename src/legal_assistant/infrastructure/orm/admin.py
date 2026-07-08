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
        "article_number",
        "note_number",
    )
    list_filter = ("book", "bab", "fasl")
    search_fields = ("external_id", "text", "article_number")
    raw_id_fields = ("document",)


@admin.register(EvaluationRecordRow)
class EvaluationRecordAdmin(admin.ModelAdmin):
    list_display = ("question", "created_at")
    search_fields = ("question", "answer", "ground_truth")
    date_hierarchy = "created_at"
