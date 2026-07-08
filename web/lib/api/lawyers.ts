import { apiFetch, qs } from "./client";
import type { Lawyer, Recommendation } from "./types";

export function listLawyers(params: {
  specialty?: string;
  location?: string;
} = {}): Promise<Lawyer[]> {
  return apiFetch<Lawyer[]>(`/api/lawyers/${qs(params)}`);
}

export function recommendLawyers(body: {
  query: string;
  location?: string;
  top_n?: number;
}): Promise<Recommendation[]> {
  return apiFetch<Recommendation[]>(`/api/lawyers/recommend/`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
