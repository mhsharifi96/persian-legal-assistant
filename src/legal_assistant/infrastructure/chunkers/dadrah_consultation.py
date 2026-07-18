from __future__ import annotations

from typing import Any

from legal_assistant.domain.models import LegalChunk, LegalDocument, LegalHierarchy
from legal_assistant.infrastructure.chunkers.persian_legal_hierarchical import (
    default_token_counter,
    split_oversized_span,
)


class DadrahConsultationChunker:
    """Create retrieval units without losing question/answer provenance."""

    def __init__(self, *, max_chunk_tokens: int = 400, chunk_overlap_tokens: int = 40) -> None:
        self._max_chunk_tokens = max_chunk_tokens
        self._chunk_overlap_tokens = chunk_overlap_tokens

    def chunk(self, document: LegalDocument) -> list[LegalChunk]:
        request_id = str(document.metadata.get("request_id") or document.id)
        question_text = self._question_text(document)
        common = {
            "source_name": "dadrah",
            "source_format": "jsonl",
            "source_uri": document.source_uri,
            "document_id": document.id,
            "document_type": document.document_type,
            "jurisdiction": document.jurisdiction,
            "request_id": request_id,
            "tags": self._tag_names(document.metadata.get("tags")),
            "trust_tier": document.metadata.get("trust_tier"),
            "parser_name": document.parser_name,
            "chunking_strategy": "dadrah_consultation_v1",
        }
        chunks = self._parts(
            document=document,
            base_id=f"{document.id}:question",
            text=question_text,
            metadata={**common, "content_role": "question"},
        )
        for position, answer in enumerate(
            document.metadata.get("_transient_answers") or (), start=1
        ):
            if not isinstance(answer, dict):
                continue
            answer_text = str(answer.get("text") or "").strip()
            if not answer_text:
                continue
            answer_number = str(answer.get("number") or position)
            lawyer = answer.get("lawyer") if isinstance(answer.get("lawyer"), dict) else {}
            combined = f"پرسش:\n{question_text}\n\nپاسخ وکیل:\n{answer_text}"
            chunks.extend(
                self._parts(
                    document=document,
                    base_id=f"{document.id}:answer:{answer_number}",
                    text=combined,
                    metadata={
                        **common,
                        "content_role": "answer",
                        "answer_number": answer_number,
                        "answer_date": answer.get("date"),
                        "answer_time": answer.get("time"),
                        "lawyer_name": lawyer.get("name"),
                        "lawyer_city": lawyer.get("city"),
                        "lawyer_profile_url": lawyer.get("profile_url"),
                    },
                )
            )
        return chunks

    def _parts(
        self,
        *,
        document: LegalDocument,
        base_id: str,
        text: str,
        metadata: dict[str, Any],
    ) -> list[LegalChunk]:
        spans = split_oversized_span(
            text,
            max_tokens=self._max_chunk_tokens,
            overlap_tokens=self._chunk_overlap_tokens,
            token_counter=default_token_counter,
        )
        part_count = len(spans)
        return [
            LegalChunk(
                id=f"{base_id}:part:{part_index}",
                document_id=document.id,
                text=text[start:end].strip(),
                hierarchy=LegalHierarchy(),
                citations=(document.source_uri,),
                metadata={
                    **metadata,
                    "char_start": start,
                    "char_end": end,
                    "part_index": part_index,
                    "part_count": part_count,
                },
            )
            for part_index, (start, end) in enumerate(spans)
            if text[start:end].strip()
        ]

    @staticmethod
    def _question_text(document: LegalDocument) -> str:
        title = document.title.removeprefix("مشاوره حقوقی رایگان - ").strip()
        return f"{title}\n{document.text}".strip()

    @staticmethod
    def _tag_names(raw_tags: Any) -> list[str]:
        if not isinstance(raw_tags, list):
            return []
        return [
            str(tag.get("name"))
            for tag in raw_tags
            if isinstance(tag, dict) and tag.get("name")
        ]
