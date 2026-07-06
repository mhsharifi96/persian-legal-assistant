from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from typing import Literal, TypedDict

from legal_assistant.domain.models import LegalChunk, LegalDocument, LegalHierarchy

CHUNKING_STRATEGY = "iranian_legal_hierarchical_v1"

HeadingKind = Literal["book", "bab", "fasl", "mabhas", "goftar"]
EventKind = HeadingKind | Literal["article", "note"]


class ChunkEvent(TypedDict):
    kind: EventKind
    value: str
    start: int


PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

HEADING_PATTERNS: dict[HeadingKind, re.Pattern[str]] = {
    "book": re.compile(r"^\s*کتاب\s+(.+)$"),
    "bab": re.compile(r"^\s*باب\s+(.+)$"),
    "fasl": re.compile(r"^\s*فصل\s+(.+)$"),
    "mabhas": re.compile(r"^\s*مبحث\s+(.+)$"),
    "goftar": re.compile(r"^\s*گفتار\s+(.+)$"),
}
HEADING_LABELS: dict[HeadingKind, str] = {
    "book": "کتاب",
    "bab": "باب",
    "fasl": "فصل",
    "mabhas": "مبحث",
    "goftar": "گفتار",
}
ARTICLE_RE = re.compile(r"^\s*ماده\s+([۰-۹٠-٩0-9]+)\s*[-:ـ]?\s*(.*)$")
NOTE_RE = re.compile(r"^\s*تبصره(?:\s+([۰-۹٠-٩0-9]+))?\s*[-:ـ]?\s*(.*)$")


class PersianLegalHierarchicalChunker:
    def chunk(self, document: LegalDocument) -> list[LegalChunk]:
        events = self._iter_events(document.text)
        chunks: list[LegalChunk] = []
        hierarchy = LegalHierarchy()
        active_start: int | None = None
        active_hierarchy: LegalHierarchy | None = None

        for event in events:
            kind = event["kind"]
            start = event["start"]

            if kind in HEADING_PATTERNS:
                if active_start is not None and active_hierarchy is not None:
                    chunks.append(
                        self._build_chunk(document, active_hierarchy, active_start, start)
                    )
                    active_start = None
                    active_hierarchy = None
                hierarchy = self._apply_heading(hierarchy, kind, event["value"])
                continue

            if kind == "article":
                if active_start is not None and active_hierarchy is not None:
                    chunks.append(
                        self._build_chunk(document, active_hierarchy, active_start, start)
                    )
                hierarchy = replace(
                    hierarchy,
                    article_number=normalize_digits(event["value"]),
                    note_number=None,
                )
                active_start = start
                active_hierarchy = hierarchy
                continue

            if kind == "note":
                if active_start is not None and active_hierarchy is not None:
                    chunks.append(
                        self._build_chunk(document, active_hierarchy, active_start, start)
                    )
                note_number = normalize_digits(event["value"]) if event["value"] else None
                active_hierarchy = replace(hierarchy, note_number=note_number)
                active_start = start

        if active_start is not None and active_hierarchy is not None:
            chunks.append(
                self._build_chunk(document, active_hierarchy, active_start, len(document.text))
            )

        return [chunk for chunk in chunks if chunk.text]

    def _iter_events(self, text: str) -> list[ChunkEvent]:
        events: list[ChunkEvent] = []
        for match in re.finditer(r"(?m)^.*$", text):
            line = match.group(0)
            if not line.strip():
                continue
            for kind, pattern in HEADING_PATTERNS.items():
                heading_match = pattern.match(line)
                if heading_match:
                    events.append(
                        {
                            "kind": kind,
                            "value": f"{HEADING_LABELS[kind]} {heading_match.group(1).strip()}",
                            "start": match.start(),
                        }
                    )
                    break
            else:
                article_match = ARTICLE_RE.match(line)
                if article_match:
                    events.append(
                        {
                            "kind": "article",
                            "value": article_match.group(1),
                            "start": match.start(),
                        }
                    )
                    continue
                note_match = NOTE_RE.match(line)
                if note_match:
                    events.append(
                        {
                            "kind": "note",
                            "value": note_match.group(1) or "",
                            "start": match.start(),
                        }
                    )
        return events

    def _apply_heading(
        self, hierarchy: LegalHierarchy, kind: HeadingKind, value: str
    ) -> LegalHierarchy:
        if kind == "book":
            return LegalHierarchy(book=value)
        if kind == "bab":
            return replace(
                hierarchy,
                bab=value,
                fasl=None,
                mabhas=None,
                goftar=None,
                article_number=None,
                note_number=None,
            )
        if kind == "fasl":
            return replace(
                hierarchy,
                fasl=value,
                mabhas=None,
                goftar=None,
                article_number=None,
                note_number=None,
            )
        if kind == "mabhas":
            return replace(
                hierarchy,
                mabhas=value,
                goftar=None,
                article_number=None,
                note_number=None,
            )
        if kind == "goftar":
            return replace(hierarchy, goftar=value, article_number=None, note_number=None)
        return hierarchy

    def _build_chunk(
        self,
        document: LegalDocument,
        hierarchy: LegalHierarchy,
        char_start: int,
        char_end: int,
    ) -> LegalChunk:
        text = document.text[char_start:char_end].strip()
        metadata = {
            "document_id": document.id,
            "source_uri": document.source_uri,
            "jurisdiction": document.jurisdiction,
            "law_title": document.title,
            "document_type": document.document_type,
            "book": hierarchy.book,
            "bab": hierarchy.bab,
            "fasl": hierarchy.fasl,
            "article_number": hierarchy.article_number,
            "note_number": hierarchy.note_number,
            "effective_date": document.effective_date,
            "publication_date": document.publication_date,
            "version": document.version,
            "page_start": document.metadata.get("page_start"),
            "page_end": document.metadata.get("page_end"),
            "char_start": char_start,
            "char_end": char_end,
            "parser_name": document.parser_name,
            "chunking_strategy": CHUNKING_STRATEGY,
        }
        citation = make_citation(document.title, hierarchy)
        return LegalChunk(
            id=make_chunk_id(document.id, hierarchy, char_start, char_end),
            document_id=document.id,
            text=text,
            hierarchy=hierarchy,
            citations=(citation,),
            metadata=metadata,
        )


def normalize_digits(value: str) -> str:
    return value.translate(PERSIAN_DIGITS)


def make_chunk_id(
    document_id: str, hierarchy: LegalHierarchy, char_start: int, char_end: int
) -> str:
    parts = [
        document_id,
        hierarchy.book or "",
        hierarchy.bab or "",
        hierarchy.fasl or "",
        hierarchy.article_number or "",
        hierarchy.note_number or "",
        str(char_start),
        str(char_end),
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{document_id}:{hierarchy.article_number or 'section'}:{hierarchy.note_number or 'article'}:{digest}"


def make_citation(title: str, hierarchy: LegalHierarchy) -> str:
    parts = [title]
    if hierarchy.book:
        parts.append(hierarchy.book)
    if hierarchy.bab:
        parts.append(hierarchy.bab)
    if hierarchy.fasl:
        parts.append(hierarchy.fasl)
    if hierarchy.article_number:
        parts.append(f"ماده {hierarchy.article_number}")
    if hierarchy.note_number:
        parts.append(f"تبصره {hierarchy.note_number}")
    return "، ".join(parts)
