from __future__ import annotations

from typing import Any, Sequence

from legal_assistant.domain.models import (
    EvaluationRecord,
    LawyerProfile,
    LegalChunk,
    LegalDocument,
    LegalHierarchy,
)
from legal_assistant.infrastructure.orm.models import (
    EvaluationRecordRow,
    LawyerRow,
    LegalChunkRow,
    LegalDocumentRow,
)

# --- mapping helpers --------------------------------------------------------


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_success_rate(value: Any) -> float:
    rate = float(value or 0.0)
    if rate > 1.0:  # tolerate 0..100 source data
        rate = rate / 100.0
    return _clamp01(rate)


def _lawyer_to_domain(row: LawyerRow) -> LawyerProfile:
    return LawyerProfile(
        lawyer_id=row.external_id,
        full_name=row.full_name,
        specialties=tuple(row.specialties or ()),
        location=row.location,
        success_rate=row.success_rate,
        metadata=dict(row.metadata or {}),
    )


def _document_to_domain(row: LegalDocumentRow) -> LegalDocument:
    return LegalDocument(
        id=row.external_id,
        title=row.title,
        source_uri=row.source_uri,
        jurisdiction=row.jurisdiction,
        document_type=row.document_type,
        text=row.text,
        effective_date=row.effective_date,
        publication_date=row.publication_date,
        version=row.version,
        parser_name=row.parser_name,
        metadata=dict(row.metadata or {}),
    )


def _chunk_to_domain(row: LegalChunkRow) -> LegalChunk:
    metadata = dict(row.metadata or {})
    hierarchy_data = metadata.get("hierarchy") or metadata
    hierarchy = LegalHierarchy(
        book=hierarchy_data.get("book"),
        bab=hierarchy_data.get("bab"),
        fasl=hierarchy_data.get("fasl"),
        mabhas=hierarchy_data.get("mabhas"),
        goftar=hierarchy_data.get("goftar"),
        article_number=hierarchy_data.get("article_number"),
        note_number=hierarchy_data.get("note_number"),
    )
    return LegalChunk(
        id=row.external_id,
        document_id=row.document_id,
        text=row.text,
        hierarchy=hierarchy,
        citations=tuple(row.citations or ()),
        metadata=metadata,
    )


def _evaluation_to_domain(row: EvaluationRecordRow) -> EvaluationRecord:
    return EvaluationRecord(
        question=row.question,
        answer=row.answer,
        contexts=tuple(row.contexts or ()),
        ground_truth=row.ground_truth,
        citations=tuple(row.citations or ()),
        metadata=dict(row.metadata or {}),
    )


def _lawyer_matches(profile: LawyerProfile, filters: dict[str, Any]) -> bool:
    for key, value in filters.items():
        if key == "specialty":
            if value not in profile.specialties:
                return False
        elif key == "location":
            if profile.location != value:
                return False
        elif profile.metadata.get(key) != value:
            return False
    return True


# --- repositories -----------------------------------------------------------


class OrmLawyerRepository:
    """Django-ORM backed ``LawyerRepository`` + ``LawyerWriteRepository``."""

    def list_lawyers(
        self, *, filters: dict[str, Any] | None = None
    ) -> list[LawyerProfile]:
        query = LawyerRow.objects.all()
        location = (filters or {}).get("location")
        if location is not None:
            query = query.filter(location=location)
        profiles = [_lawyer_to_domain(row) for row in query]
        if not filters:
            return profiles
        # JSON membership (specialty) and metadata keys are filtered in Python so
        # behaviour matches the in-memory/JSONL repositories across DB backends.
        return [p for p in profiles if _lawyer_matches(p, filters)]

    def get_lawyer(self, lawyer_id: str) -> LawyerProfile | None:
        row = LawyerRow.objects.filter(external_id=lawyer_id).first()
        return _lawyer_to_domain(row) if row is not None else None

    def upsert_lawyer(self, lawyer: LawyerProfile) -> LawyerProfile:
        row, _ = LawyerRow.objects.update_or_create(
            external_id=lawyer.lawyer_id,
            defaults={
                "full_name": lawyer.full_name,
                "specialties": list(lawyer.specialties),
                "location": lawyer.location,
                "success_rate": _normalize_success_rate(lawyer.success_rate),
                "metadata": dict(lawyer.metadata),
            },
        )
        return _lawyer_to_domain(row)

    def delete_lawyer(self, lawyer_id: str) -> bool:
        deleted, _ = LawyerRow.objects.filter(external_id=lawyer_id).delete()
        return bool(deleted)


class OrmDocumentStore:
    """Django-ORM backed ``DocumentStore``."""

    def save_document(
        self, document: LegalDocument, chunks: Any = ()
    ) -> None:
        self.save_documents([(document, chunks)])

    def save_documents(
        self,
        items: Sequence[tuple[LegalDocument, Sequence[LegalChunk]]],
    ) -> None:
        documents = [
            LegalDocumentRow(
                external_id=document.id,
                title=document.title,
                source_uri=document.source_uri,
                jurisdiction=document.jurisdiction,
                document_type=document.document_type,
                text=document.text,
                effective_date=document.effective_date,
                publication_date=document.publication_date,
                version=document.version,
                parser_name=document.parser_name,
                metadata={
                    key: value
                    for key, value in document.metadata.items()
                    if not key.startswith("_transient_")
                },
            )
            for document, _ in items
        ]
        LegalDocumentRow.objects.bulk_create(
            documents,
            batch_size=1000,
            update_conflicts=True,
            unique_fields=["external_id"],
            update_fields=[
                "title",
                "source_uri",
                "jurisdiction",
                "document_type",
                "text",
                "effective_date",
                "publication_date",
                "version",
                "parser_name",
                "metadata",
                "updated_at",
            ],
        )
        chunk_rows = [
            LegalChunkRow(
                external_id=chunk.id,
                document_id=chunk.document_id,
                text=chunk.text,
                citations=list(chunk.citations),
                metadata=self._chunk_metadata(chunk),
            )
            for _, chunks in items
            for chunk in chunks
        ]
        LegalChunkRow.objects.bulk_create(
            chunk_rows,
            batch_size=1000,
            update_conflicts=True,
            unique_fields=["external_id"],
            update_fields=["document", "text", "citations", "metadata"],
        )

    @staticmethod
    def _chunk_metadata(chunk: LegalChunk) -> dict[str, Any]:
        h = chunk.hierarchy
        metadata = dict(chunk.metadata)
        metadata["hierarchy"] = {
            "book": h.book,
            "bab": h.bab,
            "fasl": h.fasl,
            "mabhas": h.mabhas,
            "goftar": h.goftar,
            "article_number": h.article_number,
            "note_number": h.note_number,
        }
        return metadata

    def list_documents(
        self, *, filters: dict[str, Any] | None = None
    ) -> list[LegalDocument]:
        query = LegalDocumentRow.objects.all()
        for key in ("jurisdiction", "document_type"):
            value = (filters or {}).get(key)
            if value is not None:
                query = query.filter(**{key: value})
        return [_document_to_domain(row) for row in query]

    def list_chunks(
        self,
        *,
        document_id: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[LegalChunk]:
        query = LegalChunkRow.objects.all()
        if document_id is not None:
            query = query.filter(document_id=document_id)
        for key, value in (filters or {}).items():
            query = query.filter(**{f"metadata__{key}": value})
        return [_chunk_to_domain(row) for row in query]


class OrmEvaluationRepository:
    """Django-ORM backed ``EvaluationRepository`` + write side."""

    def load_records(self) -> list[EvaluationRecord]:
        return [_evaluation_to_domain(row) for row in EvaluationRecordRow.objects.all()]

    def append_record(self, record: EvaluationRecord) -> None:
        EvaluationRecordRow.objects.create(
            question=record.question,
            answer=record.answer,
            contexts=list(record.contexts),
            ground_truth=record.ground_truth,
            citations=list(record.citations),
            metadata=dict(record.metadata),
        )
