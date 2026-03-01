import RequireAuth from "@/components/RequireAuth";
import { getSessionUser } from "@/lib/auth";

export default async function DatabasePage() {
  const user = await getSessionUser();

  return (
    <RequireAuth>
      <main className="bg-white">
        <div className="mx-auto max-w-6xl px-8 py-16">
          <div className="rounded-3xl bg-white p-14 shadow-[0_20px_60px_rgba(0,0,0,0.06)]">
            <h1 className="text-4xl font-bold text-blue-900">View Database</h1>
            <p className="mt-4 text-blue-800">
              Welcome, {user?.username}. This page will display database records
              once the backend is connected.
            </p>

            <div className="mt-10 rounded-2xl bg-blue-50 px-8 py-6 text-sm text-blue-900">
              <span className="font-semibold">Status:</span> Not connected yet.
              When the DB is added, we’ll show a table here (search, filter,
              pagination).
            </div>
          </div>
        </div>
      </main>
    </RequireAuth>
  );
}