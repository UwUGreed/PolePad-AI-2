import Link from "next/link";
import RequireAuth from "@/components/RequireAuth";
import { getSessionUser } from "@/lib/auth";

export default async function PortalDashboardPage() {
  const user = await getSessionUser();

  return (
    <RequireAuth>
      <main className="bg-white">
        <div className="mx-auto max-w-6xl px-8 py-16">
          <div className="rounded-3xl bg-white p-14 shadow-[0_20px_60px_rgba(0,0,0,0.06)]">
            <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h1 className="text-4xl font-bold text-blue-900">
                  Dashboard
                </h1>
                <p className="mt-3 text-lg text-blue-800">
                  Welcome, {user?.username}. Choose an option below.
                </p>
              </div>

              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold text-blue-800">Role</span>
                <span className="rounded-full bg-blue-50 px-5 py-2 text-sm font-semibold text-blue-900">
                  {user?.role}
                </span>
              </div>
            </div>

            <div className="mt-14 grid gap-10 md:grid-cols-2">
              <CardLink
                title="Submission"
                description="Upload site photo sets (Tag, Overview, Base, Pad Mounted)."
                href="/portal/submission"
              />

              <CardLink
                title="View Database"
                description="Browse submitted records once the backend database is connected."
                href="/portal/database"
              />
            </div>
          </div>
        </div>
      </main>
    </RequireAuth>
  );
}

function CardLink({
  title,
  description,
  href,
}: {
  title: string;
  description: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="group rounded-2xl bg-white p-10 shadow-[0_10px_30px_rgba(0,0,0,0.05)] transition hover:-translate-y-[2px] hover:shadow-[0_14px_40px_rgba(0,0,0,0.08)] focus:outline-none focus:ring-2 focus:ring-blue-300"
    >
      <div className="flex items-start justify-between gap-6">
        <div>
          <h2 className="text-2xl font-semibold text-blue-900">{title}</h2>
          <p className="mt-3 text-sm text-blue-800">{description}</p>
        </div>

        <span className="rounded-lg bg-blue-50 px-4 py-2 text-xs font-semibold text-blue-900 transition group-hover:bg-blue-100">
          Open
        </span>
      </div>
    </Link>
  );
}