"use client";

import { useState } from "react";
import type { AskResponse } from "@/lib/api/types";

export function AskForm() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? "خطا در دریافت پاسخ.");
      } else {
        setResult(data as AskResponse);
      }
    } catch {
      setError("ارتباط با سرویس ممکن نشد.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={onSubmit} className="space-y-3">
        <textarea
          className="card w-full p-3"
          rows={3}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="مثال: مجازات کلاهبرداری در قانون ایران چیست؟"
        />
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="rounded-lg px-4 py-2 text-white disabled:opacity-50"
          style={{ background: "var(--accent)" }}
        >
          {loading ? "در حال پردازش…" : "پرسش"}
        </button>
      </form>

      {error && (
        <div className="card p-4 text-sm" role="alert">
          {error}
        </div>
      )}

      {result && (
        <article className="space-y-4">
          {result.insufficient_context && result.warning_fa && (
            <div className="card p-3 text-sm" role="alert">
              ⚠️ {result.warning_fa}
            </div>
          )}
          <div className="card p-4">
            <h2 className="mb-2 font-semibold">پاسخ</h2>
            <p className="whitespace-pre-wrap leading-7">{result.answer_fa}</p>
          </div>
          {result.citations.length > 0 && (
            <div className="card p-4">
              <h3 className="mb-2 font-semibold">استنادها</h3>
              <ul className="space-y-1 text-sm">
                {result.citations.map((c) => (
                  <li key={c.chunk_id}>
                    <span className="opacity-60">[{c.chunk_id}]</span> {c.text}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </article>
      )}
    </div>
  );
}
