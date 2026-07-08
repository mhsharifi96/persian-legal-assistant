from __future__ import annotations

from django.apps import AppConfig


class LegalOrmConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "legal_assistant.infrastructure.orm"
    label = "legal_orm"
    verbose_name = "Legal Assistant Data"
