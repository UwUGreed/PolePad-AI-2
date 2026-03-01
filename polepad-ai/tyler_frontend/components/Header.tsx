import Link from "next/link";
import LogoutButton from "@/components/LogoutButton";
import { getSessionUser } from "@/lib/auth";
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function Header() {
  const user = await getSessionUser();

  return (
    <header className="w-full bg-blue-900">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-8 py-6">
        <Link href="/" className="flex items-center gap-4">
          <div className="h-10 w-10 rounded bg-white/20" />
          <span className="text-3xl font-extrabold tracking-tight text-white">
            PolePadAI
          </span>
        </Link>

        <div className="flex items-center gap-4">
          {user ? (
            <>
              <Link
                href="/portal"
                className="rounded-xl bg-white/10 px-5 py-3 text-base font-semibold text-white transition hover:bg-white/15"
              >
                Dashboard
              </Link>
              <LogoutButton />
            </>
          ) : (
            <Link
              href="/login"
              className="rounded-xl bg-yellow-400 px-6 py-3 text-base font-bold text-black shadow-sm transition-all duration-150 hover:bg-yellow-300 hover:shadow-md active:scale-[0.98]"
            >
              Login
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}