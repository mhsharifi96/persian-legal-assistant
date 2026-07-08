// Shared Persian empty/error states. Never render fabricated fallback data.

export function ErrorState({ message }: { message?: string }) {
  return (
    <div className="card p-5 text-sm" role="alert">
      <p className="font-semibold">دریافت اطلاعات ممکن نشد.</p>
      <p className="opacity-70">
        {message ?? "اتصال به سرویس برقرار نشد. لطفاً بعداً دوباره تلاش کنید."}
      </p>
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="card p-5 text-sm opacity-80">
      <p>{message}</p>
    </div>
  );
}
