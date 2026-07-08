import { apiFetch, qs } from "./client";
import type { Chunk, LegalDocument } from "./types";

export function listDocuments(params: {
  jurisdiction?: string;
  document_type?: string;
} = {}): Promise<LegalDocument[]> {
  return apiFetch<LegalDocument[]>(`/api/documents/${qs(params)}`);
}

export function listChunks(documentId?: string): Promise<Chunk[]> {
  return apiFetch<Chunk[]>(`/api/chunks/${qs({ document_id: documentId })}`);
}
