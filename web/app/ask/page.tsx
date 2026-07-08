import type { Metadata } from "next";
import { AskForm } from "@/components/ask-form";

// Answers are generated per user — not indexable pages.
export const metadata: Metadata = {
  title: "پرسش حقوقی",
  description: "پرسش حقوقی خود را مطرح کنید و پاسخ مستند دریافت کنید.",
  robots: { index: false, follow: true },
};

export default function AskPage() {
  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">پرسش حقوقی</h1>
      <p className="text-sm opacity-80">
        پرسش خود را درباره حقوق ایران بنویسید. پاسخ همراه با استناد به منابع ارائه می‌شود.
      </p>
      <AskForm />
    </section>
  );
}
