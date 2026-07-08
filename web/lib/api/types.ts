// Types mirror the DRF serializer output (domain DTOs), keeping the frontend
// stable across backend persistence changes.

export interface Lawyer {
  lawyer_id: string;
  full_name: string;
  specialties: string[];
  location: string;
  success_rate: number;
  metadata: Record<string, unknown>;
}

export interface Recommendation {
  lawyer_id: string;
  full_name: string;
  score: number;
  semantic_score: number;
  success_score: number;
  location_score: number;
  rationale: string;
}

export interface Hierarchy {
  book: string | null;
  bab: string | null;
  fasl: string | null;
  mabhas: string | null;
  goftar: string | null;
  article_number: string | null;
  note_number: string | null;
}

export interface LegalDocument {
  document_id: string;
  title: string;
  source_uri: string;
  jurisdiction: string;
  document_type: string;
  effective_date: string | null;
  publication_date: string | null;
  version: string | null;
  parser_name: string;
  metadata: Record<string, unknown>;
}

export interface Chunk {
  chunk_id: string;
  document_id: string;
  text: string;
  hierarchy: Hierarchy;
  citations: string[];
  metadata: Record<string, unknown>;
}

export interface EvaluationRecord {
  question: string;
  answer: string;
  contexts: string[];
  ground_truth: string;
  citations: string[];
  metadata: Record<string, unknown>;
}

export interface MetricAggregate {
  mean: number;
  median: number;
  minimum: number;
  failures: number;
}

export interface EvaluationReport {
  metric_names: string[];
  aggregates: Record<string, MetricAggregate>;
  persian_summary: string;
  sample_count: number;
}

export interface Citation {
  chunk_id: string;
  text: string;
}

export interface AskResponse {
  answer_fa: string;
  citations: Citation[];
  insufficient_context: boolean;
  warning_fa: string | null;
  intent: string | null;
  handoff: string | null;
}
