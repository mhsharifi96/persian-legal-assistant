from __future__ import annotations

from rest_framework import serializers

# --- Lawyers ----------------------------------------------------------------


class LawyerSerializer(serializers.Serializer):
    lawyer_id = serializers.CharField()
    full_name = serializers.CharField()
    specialties = serializers.ListField(child=serializers.CharField(), default=list)
    location = serializers.CharField(allow_blank=True, default="")
    success_rate = serializers.FloatField(default=0.0)
    metadata = serializers.DictField(default=dict)


class LawyerWriteSerializer(serializers.Serializer):
    lawyer_id = serializers.CharField(max_length=128)
    full_name = serializers.CharField(max_length=255)
    specialties = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    location = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    success_rate = serializers.FloatField(required=False, default=0.0)
    metadata = serializers.DictField(required=False, default=dict)


class RecommendationRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    location = serializers.CharField(required=False, allow_blank=True)
    top_n = serializers.IntegerField(required=False, min_value=1, max_value=100)


class RecommendationSerializer(serializers.Serializer):
    lawyer_id = serializers.CharField()
    full_name = serializers.CharField()
    score = serializers.FloatField()
    semantic_score = serializers.FloatField()
    success_score = serializers.FloatField()
    location_score = serializers.FloatField()
    rationale = serializers.CharField()


# --- Documents & chunks -----------------------------------------------------


class DocumentSerializer(serializers.Serializer):
    document_id = serializers.CharField()
    title = serializers.CharField()
    source_uri = serializers.CharField(allow_blank=True)
    jurisdiction = serializers.CharField()
    document_type = serializers.CharField(allow_blank=True)
    effective_date = serializers.CharField(allow_null=True, required=False)
    publication_date = serializers.CharField(allow_null=True, required=False)
    version = serializers.CharField(allow_null=True, required=False)
    parser_name = serializers.CharField()
    metadata = serializers.DictField(default=dict)


class HierarchySerializer(serializers.Serializer):
    book = serializers.CharField(allow_null=True, required=False)
    bab = serializers.CharField(allow_null=True, required=False)
    fasl = serializers.CharField(allow_null=True, required=False)
    mabhas = serializers.CharField(allow_null=True, required=False)
    goftar = serializers.CharField(allow_null=True, required=False)
    article_number = serializers.CharField(allow_null=True, required=False)
    note_number = serializers.CharField(allow_null=True, required=False)


class ChunkSerializer(serializers.Serializer):
    chunk_id = serializers.CharField()
    document_id = serializers.CharField()
    text = serializers.CharField()
    hierarchy = HierarchySerializer()
    citations = serializers.ListField(child=serializers.CharField(), default=list)
    metadata = serializers.DictField(default=dict)


# --- Evaluation -------------------------------------------------------------


class EvaluationRecordSerializer(serializers.Serializer):
    question = serializers.CharField()
    answer = serializers.CharField(required=False, allow_blank=True, default="")
    contexts = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    ground_truth = serializers.CharField(required=False, allow_blank=True, default="")
    citations = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    metadata = serializers.DictField(required=False, default=dict)


class MetricAggregateSerializer(serializers.Serializer):
    mean = serializers.FloatField()
    median = serializers.FloatField()
    minimum = serializers.FloatField()
    failures = serializers.IntegerField()


class EvaluationReportSerializer(serializers.Serializer):
    metric_names = serializers.ListField(child=serializers.CharField())
    aggregates = serializers.DictField(child=MetricAggregateSerializer())
    persian_summary = serializers.CharField()
    sample_count = serializers.IntegerField()


# --- Agentic Q&A ------------------------------------------------------------


class AskRequestSerializer(serializers.Serializer):
    question = serializers.CharField()
    thread_id = serializers.CharField(required=False, allow_blank=True)


class CitationSerializer(serializers.Serializer):
    chunk_id = serializers.CharField()
    text = serializers.CharField(allow_blank=True)


class AskResponseSerializer(serializers.Serializer):
    answer_fa = serializers.CharField()
    citations = CitationSerializer(many=True)
    insufficient_context = serializers.BooleanField()
    warning_fa = serializers.CharField(allow_blank=True, allow_null=True)
    intent = serializers.CharField(allow_null=True)
    handoff = serializers.CharField(allow_null=True)
