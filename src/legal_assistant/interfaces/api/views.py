from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from legal_assistant.domain.models import (
    Citation,
    LawyerProfile,
    LawyerRecommendation,
    LegalChunk,
    LegalDocument,
)
from legal_assistant.interfaces.api import container, serializers

# --- domain -> dict mappers -------------------------------------------------


def _lawyer_to_dict(p: LawyerProfile) -> dict[str, Any]:
    return {
        "lawyer_id": p.lawyer_id,
        "full_name": p.full_name,
        "specialties": list(p.specialties),
        "location": p.location,
        "success_rate": p.success_rate,
        "metadata": dict(p.metadata),
    }


def _recommendation_to_dict(r: LawyerRecommendation) -> dict[str, Any]:
    return {
        "lawyer_id": r.lawyer_id,
        "full_name": r.full_name,
        "score": r.score,
        "semantic_score": r.semantic_score,
        "success_score": r.success_score,
        "location_score": r.location_score,
        "rationale": r.rationale,
    }


def _document_to_dict(d: LegalDocument) -> dict[str, Any]:
    return {
        "document_id": d.id,
        "title": d.title,
        "source_uri": d.source_uri,
        "jurisdiction": d.jurisdiction,
        "document_type": d.document_type,
        "effective_date": d.effective_date,
        "publication_date": d.publication_date,
        "version": d.version,
        "parser_name": d.parser_name,
        "metadata": dict(d.metadata),
    }


def _chunk_to_dict(c: LegalChunk) -> dict[str, Any]:
    h = c.hierarchy
    return {
        "chunk_id": c.id,
        "document_id": c.document_id,
        "text": c.text,
        "hierarchy": {
            "book": h.book,
            "bab": h.bab,
            "fasl": h.fasl,
            "mabhas": h.mabhas,
            "goftar": h.goftar,
            "article_number": h.article_number,
            "note_number": h.note_number,
        },
        "citations": list(c.citations),
        "metadata": dict(c.metadata),
    }


def _citation_to_dict(c: Citation) -> dict[str, Any]:
    return {"chunk_id": c.chunk_id, "text": c.text}


# --- Lawyers ----------------------------------------------------------------


class LawyerListView(APIView):
    def get_permissions(self):  # type: ignore[override]
        return [IsAdminUser()] if self.request.method == "POST" else [AllowAny()]

    def get(self, request: Request) -> Response:
        filters: dict[str, Any] = {}
        if specialty := request.query_params.get("specialty"):
            filters["specialty"] = specialty
        if location := request.query_params.get("location"):
            filters["location"] = location
        profiles = container.lawyer_repository().list_lawyers(filters=filters or None)
        data = [_lawyer_to_dict(p) for p in profiles]
        return Response(serializers.LawyerSerializer(data, many=True).data)

    def post(self, request: Request) -> Response:
        serializer = serializers.LawyerWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        repo = container.lawyer_repository()
        if not hasattr(repo, "upsert_lawyer"):
            return Response(
                {"detail": "The active lawyer repository is read-only."},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )
        v = serializer.validated_data
        profile = LawyerProfile(
            lawyer_id=v["lawyer_id"],
            full_name=v["full_name"],
            specialties=tuple(v["specialties"]),
            location=v["location"],
            success_rate=float(v["success_rate"]),
            metadata=dict(v["metadata"]),
        )
        saved = repo.upsert_lawyer(profile)  # type: ignore[attr-defined]
        return Response(
            serializers.LawyerSerializer(_lawyer_to_dict(saved)).data,
            status=status.HTTP_201_CREATED,
        )


class LawyerDetailView(APIView):
    def get_permissions(self):  # type: ignore[override]
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [IsAdminUser()]
        return [AllowAny()]

    def _get_repo(self):
        return container.lawyer_repository()

    def get(self, request: Request, lawyer_id: str) -> Response:
        repo = self._get_repo()
        profile = None
        if hasattr(repo, "get_lawyer"):
            profile = repo.get_lawyer(lawyer_id)  # type: ignore[attr-defined]
        else:
            matches = [
                p for p in repo.list_lawyers() if p.lawyer_id == lawyer_id
            ]
            profile = matches[0] if matches else None
        if profile is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(serializers.LawyerSerializer(_lawyer_to_dict(profile)).data)

    def put(self, request: Request, lawyer_id: str) -> Response:
        repo = self._get_repo()
        if not hasattr(repo, "upsert_lawyer"):
            return Response(
                {"detail": "The active lawyer repository is read-only."},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )
        serializer = serializers.LawyerWriteSerializer(data={**request.data, "lawyer_id": lawyer_id})
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        profile = LawyerProfile(
            lawyer_id=lawyer_id,
            full_name=v["full_name"],
            specialties=tuple(v["specialties"]),
            location=v["location"],
            success_rate=float(v["success_rate"]),
            metadata=dict(v["metadata"]),
        )
        saved = repo.upsert_lawyer(profile)  # type: ignore[attr-defined]
        return Response(serializers.LawyerSerializer(_lawyer_to_dict(saved)).data)

    def delete(self, request: Request, lawyer_id: str) -> Response:
        repo = self._get_repo()
        if not hasattr(repo, "delete_lawyer"):
            return Response(
                {"detail": "The active lawyer repository is read-only."},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )
        deleted = repo.delete_lawyer(lawyer_id)  # type: ignore[attr-defined]
        return Response(
            status=status.HTTP_204_NO_CONTENT
            if deleted
            else status.HTTP_404_NOT_FOUND
        )


class LawyerRecommendView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = serializers.RecommendationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        results = container.recommendation_service().recommend(
            v["query"],
            location=v.get("location") or None,
            top_n=v.get("top_n"),
        )
        data = [_recommendation_to_dict(r) for r in results]
        return Response(serializers.RecommendationSerializer(data, many=True).data)


# --- Documents & chunks -----------------------------------------------------


class DocumentListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        filters: dict[str, Any] = {}
        for key in ("jurisdiction", "document_type"):
            if value := request.query_params.get(key):
                filters[key] = value
        documents = container.document_store().list_documents(filters=filters or None)
        data = [_document_to_dict(d) for d in documents]
        return Response(serializers.DocumentSerializer(data, many=True).data)


class ChunkListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        document_id = request.query_params.get("document_id")
        chunks = container.document_store().list_chunks(document_id=document_id)
        data = [_chunk_to_dict(c) for c in chunks]
        return Response(serializers.ChunkSerializer(data, many=True).data)


# --- Evaluation -------------------------------------------------------------


class EvaluationListView(APIView):
    def get_permissions(self):  # type: ignore[override]
        return [IsAdminUser()] if self.request.method == "POST" else [AllowAny()]

    def get(self, request: Request) -> Response:
        records = container.evaluation_repository().load_records()
        data = [
            {
                "question": r.question,
                "answer": r.answer,
                "contexts": list(r.contexts),
                "ground_truth": r.ground_truth,
                "citations": list(r.citations),
                "metadata": dict(r.metadata),
            }
            for r in records
        ]
        return Response(serializers.EvaluationRecordSerializer(data, many=True).data)

    def post(self, request: Request) -> Response:
        from legal_assistant.domain.models import EvaluationRecord

        serializer = serializers.EvaluationRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        repo = container.evaluation_repository()
        if not hasattr(repo, "append_record"):
            return Response(
                {"detail": "The active evaluation repository is read-only."},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )
        v = serializer.validated_data
        repo.append_record(  # type: ignore[attr-defined]
            EvaluationRecord(
                question=v["question"],
                answer=v["answer"],
                contexts=tuple(v["contexts"]),
                ground_truth=v["ground_truth"],
                citations=tuple(v["citations"]),
                metadata=dict(v["metadata"]),
            )
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class EvaluationRunView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        report = container.evaluation_service().evaluate_repository(
            container.evaluation_repository()
        )
        payload = {
            "metric_names": list(report.metric_names),
            "aggregates": {
                name: {
                    "mean": agg.mean,
                    "median": agg.median,
                    "minimum": agg.minimum,
                    "failures": agg.failures,
                }
                for name, agg in report.aggregates.items()
            },
            "persian_summary": report.persian_summary,
            "sample_count": len(report.samples),
        }
        return Response(serializers.EvaluationReportSerializer(payload).data)


# --- Agentic Q&A ------------------------------------------------------------


class AskView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = serializers.AskRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings = container.settings()
        if settings.api_require_real_llm and settings.llm_provider == "fake":
            return Response(
                {
                    "detail": "پاسخ‌گویی نیازمند ارائه‌دهنده واقعی مدل زبانی است؛ "
                    "پیکربندی فعلی از حالت آزمایشی استفاده می‌کند."
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        v = serializer.validated_data
        state = container.agentic_graph().run(
            v["question"], thread_id=v.get("thread_id") or None
        )
        payload = {
            "answer_fa": state.draft_response,
            "citations": [_citation_to_dict(c) for c in state.citations],
            "insufficient_context": state.limited,
            "warning_fa": (
                "پاسخ با بافت ناکافی تولید شده است؛ لطفاً با احتیاط استفاده کنید."
                if state.limited
                else None
            ),
            "intent": state.intent,
            "handoff": state.handoff,
        }
        return Response(serializers.AskResponseSerializer(payload).data)


# --- Health -----------------------------------------------------------------


class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        s = container.settings()
        return Response(
            {
                "status": "ok",
                "lawyer_repo_provider": s.lawyer_repo_provider,
                "llm_provider": s.llm_provider,
            }
        )
