from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


@dataclass(frozen=True)
class DocumentSource:
    id: str
    title: str
    file_url: str | None
    local_address_file: str | None


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    document_id: str
    title: str
    text: str
    index: int
    count: int
    file_url: str | None
    local_address_file: str | None


class DocumentRepository(Protocol):
    def upsert(self, document: DocumentSource) -> None: ...

    def mark_indexed(self, document_id: str, point_count: int) -> None: ...

    def mark_failed(self, document_id: str, error: str) -> None: ...


class PdfTextExtractor(Protocol):
    def extract(self, path: Path) -> str: ...


class EmbeddingProvider(Protocol):
    @property
    def dimension(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class DocumentVectorStore(Protocol):
    def replace_document(
        self,
        document_id: str,
        chunks: Sequence[DocumentChunk],
        vectors: Sequence[list[float]],
        *,
        dimension: int,
    ) -> None: ...


def split_text(text: str, *, max_chars: int, overlap_chars: int) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be between zero and max_chars")
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        if end < len(normalized):
            natural_break = max(
                normalized.rfind("\n", start, end),
                normalized.rfind(". ", start, end),
                normalized.rfind(".\n", start, end),
            )
            if natural_break > start + max_chars // 2:
                end = natural_break + 1
        chunks.append(normalized[start:end].strip())
        if end >= len(normalized):
            break
        start = end - overlap_chars
    return [chunk for chunk in chunks if chunk]


class DocumentIngestionService:
    def __init__(
        self,
        repository: DocumentRepository,
        extractor: PdfTextExtractor,
        embeddings: EmbeddingProvider,
        vector_store: DocumentVectorStore,
        *,
        max_chunk_chars: int = 4000,
        chunk_overlap_chars: int = 300,
    ) -> None:
        self._repository = repository
        self._extractor = extractor
        self._embeddings = embeddings
        self._vector_store = vector_store
        self._max_chunk_chars = max_chunk_chars
        self._chunk_overlap_chars = chunk_overlap_chars

    def ingest(self, document: DocumentSource) -> int:
        self._repository.upsert(document)
        try:
            if not document.local_address_file:
                raise ValueError("local_address_file is required for PDF ingestion")
            path = Path(document.local_address_file)
            if not path.is_file():
                raise FileNotFoundError(f"PDF file not found: {path}")
            extracted = self._extractor.extract(path)
            pieces = split_text(
                extracted,
                max_chars=self._max_chunk_chars,
                overlap_chars=self._chunk_overlap_chars,
            )
            if not pieces:
                pieces = [document.title]
            count = len(pieces)
            chunks = [
                DocumentChunk(
                    id=self._chunk_id(document.id, index, text),
                    document_id=document.id,
                    title=document.title,
                    text=text,
                    index=index,
                    count=count,
                    file_url=document.file_url,
                    local_address_file=document.local_address_file,
                )
                for index, text in enumerate(pieces, start=1)
            ]
            embedding_inputs = [f"{document.title}\n\n{chunk.text}" for chunk in chunks]
            vectors = self._embeddings.embed(embedding_inputs)
            if len(vectors) != len(chunks):
                raise ValueError("Embedding provider returned an unexpected vector count")
            self._vector_store.replace_document(
                document.id,
                chunks,
                vectors,
                dimension=self._embeddings.dimension,
            )
            self._repository.mark_indexed(document.id, len(chunks))
            return len(chunks)
        except Exception as exc:
            self._repository.mark_failed(document.id, str(exc))
            raise

    @staticmethod
    def _chunk_id(document_id: str, index: int, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return f"{document_id}:chunk:{index}:{digest}"
