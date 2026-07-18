from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LegalDocument:
    id: str
    title: str
    source_uri: str
    jurisdiction: str
    document_type: str
    text: str
    effective_date: str | None = None
    publication_date: str | None = None
    version: str | None = None
    parser_name: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LegalHierarchy:
    book: str | None = None
    bab: str | None = None
    fasl: str | None = None
    mabhas: str | None = None
    goftar: str | None = None
    article_number: str | None = None
    note_number: str | None = None


@dataclass(frozen=True)
class LegalChunk:
    id: str
    document_id: str
    text: str
    hierarchy: LegalHierarchy
    citations: tuple[str, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RetrievedContext:
    chunk_id: str
    text: str
    score: float
    source: str
    hierarchy: LegalHierarchy
    citations: tuple[str, ...] = ()
    graph_neighbors: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Citation:
    """A structured, verifiable reference to a retrieved chunk.

    ``chunk_id`` is the grounding key the judge checks against
    ``retrieved_context`` (reliable), while ``text`` is the rendered Persian
    citation string used only for display.
    """

    chunk_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEntity:
    id: str
    type: str
    name: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphRelation:
    source_id: str
    target_id: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphExtraction:
    entities: tuple[GraphEntity, ...] = ()
    relations: tuple[GraphRelation, ...] = ()


@dataclass(frozen=True)
class IngestionErrorRecord:
    document_id: str
    chunk_id: str
    stage: str
    error_message: str


# --- Phase 3: recommendation and evaluation ---------------------------------


@dataclass(frozen=True)
class LawyerProfile:
    lawyer_id: str
    full_name: str
    specialties: tuple[str, ...]
    location: str
    success_rate: float  # normalized to 0..1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LawyerRecommendation:
    lawyer_id: str
    full_name: str
    score: float
    semantic_score: float
    success_score: float
    location_score: float
    rationale: str


@dataclass(frozen=True)
class EvaluationRecord:
    question: str
    answer: str
    contexts: tuple[str, ...]
    ground_truth: str
    citations: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
