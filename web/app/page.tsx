import Link from "next/link";

const FEATURES = [
  {
    href: "/ask",
    title: "پرسش حقوقی",
    body: "پرسش خود را مطرح کنید و پاسخ مستند به منابع قانونی ایران دریافت کنید.",
  },
  {
    href: "/lawyers",
    title: "یافتن وکیل",
    body: "بر اساس تخصص و محل، وکیل مناسب را با امتیاز شفاف پیشنهاد بگیرید.",
  },
  {
    href: "/documents",
    title: "اسناد قانونی",
    body: "اسناد و مواد قانونی ایران را همراه با ساختار سلسله‌مراتبی مرور کنید.",
  },
  {
    href: "/evaluations",
    title: "ارزیابی کیفیت",
    body: "شاخص‌های کیفیت پاسخ‌ها و میزان استناد را مشاهده کنید.",
  },
];

export default function HomePage() {
  return (
    <section className="space-y-8">
      <div className="space-y-3">
        <h1 className="text-3xl font-bold">دستیار حقوقی هوشمند ایران</h1>
        <p className="text-base opacity-80">
          پاسخ‌های مستند حقوقی، پیشنهاد وکیل و مرور اسناد قانونی — بر پایه داده‌های واقعی.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {FEATURES.map((f) => (
          <Link key={f.href} href={f.href} className="card block p-5 hover:shadow">
            <h2 className="mb-2 text-lg font-semibold">{f.title}</h2>
            <p className="text-sm opacity-80">{f.body}</p>
          </Link>
        ))}
      </div>
    </section>
  );
}
