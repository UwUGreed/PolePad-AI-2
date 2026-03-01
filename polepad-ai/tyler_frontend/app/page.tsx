import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-14 bg-white">
      <div className="rounded-3xl border bg-white p-10 shadow-sm">
        <h1 className="text-4xl font-bold tracking-tight text-blue-900">
          Welcome to PalpadAI
        </h1>

        <p className="mt-3 text-blue-800 max-w-2xl">
          Secure access for authorized users. Accounts are created by an
          administrator.
        </p>

        <div className="mt-8 flex flex-wrap gap-3">
          <Link
            href="/login"
            className="rounded-xl bg-yellow-400 px-5 py-3 font-semibold text-black hover:bg-yellow-300 transition"
          >
            Login
          </Link>

          <Link
            href="/portal"
            className="rounded-xl border border-blue-700 px-5 py-3 font-semibold text-blue-900 hover:bg-blue-50 transition"
          >
            Go to Portal
          </Link>
        </div>
      </div>
    </main>
  );
}