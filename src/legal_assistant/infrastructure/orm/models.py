from __future__ import annotations

from django.db import models


class LawyerRow(models.Model):
    """Persistence row for a lawyer profile (maps to domain ``LawyerProfile``)."""

    external_id = models.CharField(max_length=128, unique=True, db_index=True)
    full_name = models.CharField(max_length=255)
    specialties = models.JSONField(default=list, blank=True)
    location = models.CharField(max_length=255, blank=True)
    # Normalized to 0..1 (contract requirement enforced by the adapter).
    success_rate = models.FloatField(default=0.0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "legal_lawyer"
        ordering = ["full_name"]
        verbose_name = "lawyer"
        verbose_name_plural = "lawyers"

    def __str__(self) -> str:
        return f"{self.full_name} ({self.external_id})"


class LegalDocumentRow(models.Model):
    """Persistence row for an ingested legal document."""

    external_id = models.CharField(max_length=128, unique=True, db_index=True)
    title = models.CharField(max_length=512)
    source_uri = models.CharField(max_length=1024, blank=True)
    jurisdiction = models.CharField(max_length=32, default="IR", db_index=True)
    document_type = models.CharField(max_length=64, blank=True, db_index=True)
    text = models.TextField(blank=True)
    effective_date = models.CharField(max_length=32, blank=True, null=True)
    publication_date = models.CharField(max_length=32, blank=True, null=True)
    version = models.CharField(max_length=64, blank=True, null=True)
    parser_name = models.CharField(max_length=64, default="unknown")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "legal_document"
        ordering = ["title"]
        verbose_name = "legal document"
        verbose_name_plural = "legal documents"

    def __str__(self) -> str:
        return f"{self.title} ({self.external_id})"


class LegalChunkRow(models.Model):
    """Persistence row for a legal chunk with full Iranian hierarchy metadata."""

    external_id = models.CharField(max_length=160, unique=True, db_index=True)
    document = models.ForeignKey(
        LegalDocumentRow,
        on_delete=models.CASCADE,
        related_name="chunks",
        to_field="external_id",
        db_column="document_external_id",
    )
    text = models.TextField()
    # Iranian legal hierarchy (کتاب/باب/فصل/مبحث/گفتار/ماده/تبصره).
    book = models.CharField(max_length=128, blank=True, null=True)
    bab = models.CharField(max_length=128, blank=True, null=True)
    fasl = models.CharField(max_length=128, blank=True, null=True)
    mabhas = models.CharField(max_length=128, blank=True, null=True)
    goftar = models.CharField(max_length=128, blank=True, null=True)
    article_number = models.CharField(
        max_length=64, blank=True, null=True, db_index=True
    )
    note_number = models.CharField(max_length=64, blank=True, null=True)
    citations = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "legal_chunk"
        ordering = ["document_id", "external_id"]
        verbose_name = "legal chunk"
        verbose_name_plural = "legal chunks"

    def __str__(self) -> str:
        return self.external_id


class EvaluationRecordRow(models.Model):
    """Persistence row for a RAGAS-style evaluation record."""

    question = models.TextField()
    answer = models.TextField(blank=True)
    contexts = models.JSONField(default=list, blank=True)
    ground_truth = models.TextField(blank=True)
    citations = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "legal_evaluation_record"
        ordering = ["-created_at"]
        verbose_name = "evaluation record"
        verbose_name_plural = "evaluation records"

    def __str__(self) -> str:
        return self.question[:80]
