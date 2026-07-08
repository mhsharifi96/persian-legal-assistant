import type { Metadata } from "next";
import { listDocuments } from "@/lib/api/documents";
import type { LegalDocument } from "@/lib/api/types";
import { EmptyState, ErrorState } from "@/components/states";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "اسناد قانونی",
  description: "مرور اسناد و قوانین ایران به همراه فراداده سلسله‌مراتبی.",
  alternates: { canonical: "/documents" },
};

export default async function DocumentsPage() {
  let documents: LegalDocument[] = [];
  let failed = false;
  try {
    documents = await listDocuments();
  } catch {
    failed = true;
  }

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">اسناد قانونی</h1>
      {failed ? (
        <ErrorState />
      ) : documents.length === 0 ? (
        <EmptyState message="هنوز سند قانونی وارد نشده است." />
      ) : (
        <ul className="space-y-3">
          {documents.map((doc) => (
            <li key={doc.document_id} className="card p-4">
              <h2 className="text-lg font-semibold">{doc.title}</h2>
              <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm opacity-80">
                <dt>نوع سند</dt>
                <dd>{doc.document_type || "—"}</dd>
                <dt>حوزه قضایی</dt>
                <dd>{doc.jurisdiction}</dd>
                <dt>نسخه</dt>
                <dd>{doc.version || "—"}</dd>
                <dt>تاریخ اجرا</dt>
                <dd>{doc.effective_date || "—"}</dd>
              </dl>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
