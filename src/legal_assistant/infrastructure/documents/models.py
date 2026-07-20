from __future__ import annotations

from django.db import models


class LegalFile(models.Model):
    class IngestionStatus(models.TextChoices):
        PENDING = "pending", "در انتظار"
        INDEXED = "indexed", "نمایه‌سازی شده"
        FAILED = "failed", "ناموفق"

    id = models.CharField(primary_key=True, max_length=128)
    title = models.CharField(max_length=512)
    file_url = models.URLField(max_length=2048, null=True, blank=True)
    local_address_file = models.TextField(null=True, blank=True)
    ingestion_status = models.CharField(
        max_length=16,
        choices=IngestionStatus.choices,
        default=IngestionStatus.PENDING,
    )
    qdrant_points = models.PositiveIntegerField(default=0)
    ingestion_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("id",)
        verbose_name = "فایل حقوقی"
        verbose_name_plural = "فایل‌های حقوقی"

    def __str__(self) -> str:
        return self.title
