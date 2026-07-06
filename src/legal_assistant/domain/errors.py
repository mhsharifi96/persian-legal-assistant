class LegalAssistantError(Exception):
    """Base error for the Persian legal assistant."""


class GraphExtractionError(LegalAssistantError):
    """Raised when graph extraction output cannot be validated."""


class IngestionError(LegalAssistantError):
    """Raised when document ingestion fails."""
