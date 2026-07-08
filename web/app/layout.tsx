import type { Metadata } from "next";
import { Vazirmatn } from "next/font/google";
import Link from "next/link";
import "./globals.css";

// Self-hosted Persian font (Next downloads and serves it locally — no CDN).
const vazirmatn = Vazirmatn({
  subsets: ["arabic"],
  variable: "--font-vazirmatn",
  display: "swap",
});

const SITE_URL = process.env.SITE_URL ?? "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "دستیار حقوقی هوشمند",
    template: "%s | دستیار حقوقی هوشمند",
  },
  description:
    "دستیار حقوقی هوشمند برای حقوق ایران: جست‌وجوی وکیل، مرور اسناد قانونی و پاسخ مستند به پرسش‌های حقوقی.",
  openGraph: {
    locale: "fa_IR",
    type: "website",
    title: "دستیار حقوقی هوشمند",
  },
};

const NAV = [
  { href: "/", label: "خانه" },
  { href: "/ask", label: "پرسش حقوقی" },
  { href: "/lawyers", label: "وکلا" },
  { href: "/documents", label: "اسناد قانونی" },
  { href: "/evaluations", label: "ارزیابی" },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fa" dir="rtl" className={vazirmatn.variable}>
      <body className="font-sans min-h-screen">
        <header className="border-b" style={{ borderColor: "var(--border)" }}>
          <nav className="mx-auto flex max-w-5xl flex-wrap items-center gap-4 p-4">
            <span className="font-bold text-lg">دستیار حقوقی</span>
            <ul className="flex flex-wrap gap-4 text-sm">
              {NAV.map((item) => (
                <li key={item.href}>
                  <Link href={item.href} className="hover:underline">
                    {item.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </header>
        <main className="mx-auto max-w-5xl p-4 md:p-6">{children}</main>
      </body>
    </html>
  );
}
