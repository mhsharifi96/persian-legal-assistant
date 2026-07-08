import { NextResponse } from "next/server";
import { ask } from "@/lib/api/ask";
import { ApiError } from "@/lib/api/client";

// Server-side proxy (BFF): the browser calls this same-origin route, which
// reaches the Django API using the server-only API_BASE_URL. No CORS, no
// exposed backend host.
export async function POST(request: Request) {
  let body: { question?: string; thread_id?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "درخواست نامعتبر است." }, { status: 400 });
  }
  if (!body.question || !body.question.trim()) {
    return NextResponse.json({ detail: "پرسش را وارد کنید." }, { status: 400 });
  }
  try {
    const data = await ask({ question: body.question, thread_id: body.thread_id });
    return NextResponse.json(data);
  } catch (error) {
    const status = error instanceof ApiError && error.status ? error.status : 502;
    const detail =
      error instanceof ApiError ? error.detail : "خطا در ارتباط با سرویس.";
    return NextResponse.json({ detail }, { status });
  }
}
