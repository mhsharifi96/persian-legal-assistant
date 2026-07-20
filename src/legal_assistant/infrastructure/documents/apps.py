from django.apps import AppConfig


class LegalDocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "legal_assistant.infrastructure.documents"
    label = "legal_documents"
    verbose_name = "اسناد حقوقی"
