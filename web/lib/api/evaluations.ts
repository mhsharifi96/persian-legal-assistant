import { apiFetch } from "./client";
import type { EvaluationRecord, EvaluationReport } from "./types";

export function listEvaluations(): Promise<EvaluationRecord[]> {
  return apiFetch<EvaluationRecord[]>(`/api/evaluations/`);
}

export function runEvaluation(): Promise<EvaluationReport> {
  return apiFetch<EvaluationReport>(`/api/evaluations/run/`, {
    method: "POST",
    body: "{}",
  });
}
