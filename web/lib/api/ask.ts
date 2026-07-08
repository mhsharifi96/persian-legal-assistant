import { apiFetch } from "./client";
import type { AskResponse } from "./types";

export function ask(body: {
  question: string;
  thread_id?: string;
}): Promise<AskResponse> {
  return apiFetch<AskResponse>(`/api/ask/`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
