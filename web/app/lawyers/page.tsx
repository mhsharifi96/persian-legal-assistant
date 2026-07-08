import type { Metadata } from "next";
import { listLawyers } from "@/lib/api/lawyers";
import type { Lawyer } from "@/lib/api/types";
import { EmptyState, ErrorState } from "@/components/states";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "وکلا",
  description: "فهرست وکلای حقوقی به همراه تخصص، محل و نرخ موفقیت.",
  alternates: { canonical: "/lawyers" },
};

export default async function LawyersPage() {
  let lawyers: Lawyer[] = [];
  let failed = false;
  try {
    lawyers = await listLawyers();
  } catch {
    failed = true;
  }

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">وکلا</h1>
      {failed ? (
        <ErrorState />
      ) : lawyers.length === 0 ? (
        <EmptyState message="هنوز وکیلی ثبت نشده است." />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {lawyers.map((lawyer) => (
            <li key={lawyer.lawyer_id} className="card p-4">
              <h2 className="text-lg font-semibold">{lawyer.full_name}</h2>
              <p className="text-sm opacity-80">{lawyer.location || "—"}</p>
              <p className="mt-2 text-sm">
                تخصص‌ها: {lawyer.specialties.join("، ") || "نامشخص"}
              </p>
              <p className="mt-1 text-sm">
                نرخ موفقیت: {(lawyer.success_rate * 100).toFixed(0)}٪
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
