import type { Metadata } from "next";
import { runEvaluation } from "@/lib/api/evaluations";
import type { EvaluationReport } from "@/lib/api/types";
import { EmptyState, ErrorState } from "@/components/states";

export const dynamic = "force-dynamic";

// Authenticated/internal quality surface — keep it out of the index.
export const metadata: Metadata = {
  title: "ارزیابی کیفیت",
  description: "شاخص‌های کیفیت پاسخ‌های حقوقی.",
  robots: { index: false, follow: false },
};

const METRIC_LABELS: Record<string, string> = {
  context_precision: "دقت بافت",
  faithfulness: "وفاداری",
  answer_relevancy: "ارتباط پاسخ",
  citation_grounding: "استناد",
  jurisdiction: "حوزه قضایی",
};

export default async function EvaluationsPage() {
  let report: EvaluationReport | null = null;
  let failed = false;
  try {
    report = await runEvaluation();
  } catch {
    failed = true;
  }

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">ارزیابی کیفیت پاسخ‌ها</h1>
      {failed ? (
        <ErrorState />
      ) : !report || report.sample_count === 0 ? (
        <EmptyState message="هنوز داده‌ای برای ارزیابی وجود ندارد." />
      ) : (
        <>
          <p className="text-sm opacity-80">
            تعداد نمونه‌ها: {report.sample_count}
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {report.metric_names.map((name) => {
              const agg = report!.aggregates[name];
              return (
                <div key={name} className="card p-4">
                  <h2 className="text-sm font-semibold">
                    {METRIC_LABELS[name] ?? name}
                  </h2>
                  <p className="mt-2 text-2xl font-bold">
                    {(agg.mean * 100).toFixed(0)}٪
                  </p>
                  <p className="text-xs opacity-70">
                    میانه {(agg.median * 100).toFixed(0)}٪ · ناموفق {agg.failures}
                  </p>
                </div>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
