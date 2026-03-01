"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;

    setErr(null);
    setLoading(true);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000); // 10s safety

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
        signal: controller.signal,
      });

      const raw = await res.text(); // ✅ never hangs
      let data: any = null;
      try {
        data = raw ? JSON.parse(raw) : null;
      } catch {
        data = null;
      }

      if (!res.ok) {
        setErr(data?.error || raw || `Login failed (${res.status})`);
        return;
      }

      // If server forgot to send role, default to portal
      const role = data?.role;
      router.push(role === "admin" ? "/admin" : "/portal");
      router.refresh();
    } catch (e: any) {
      setErr(e?.name === "AbortError" ? "Login timed out." : (e?.message || "Network error"));
    } finally {
      clearTimeout(timeout);
      setLoading(false); // ✅ ALWAYS stops “Signing in...”
    }
  }

  return (
    <main className="min-h-[calc(100vh-80px)] flex items-center justify-center bg-white px-4">
      <div className="w-full max-w-md rounded-2xl border-2 border-blue-600 bg-white p-8 shadow-md">
        <h1 className="text-3xl font-bold text-blue-900">Sign in</h1>
        <p className="mt-2 text-sm text-blue-800">Enter your username and password.</p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label className="text-sm font-semibold text-blue-900">Username</label>
            <input
              className="mt-1 w-full rounded-xl border border-blue-200 px-3 py-2 text-blue-900 placeholder:text-blue-400 outline-none focus:ring-2 focus:ring-blue-500"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
            />
          </div>

          <div>
            <label className="text-sm font-semibold text-blue-900">Password</label>
            <input
              type="password"
              className="mt-1 w-full rounded-xl border border-blue-200 px-3 py-2 text-blue-900 placeholder:text-blue-400 outline-none focus:ring-2 focus:ring-blue-500"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>

          {err && (
            <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {err}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-xl bg-yellow-400 px-4 py-2 font-semibold text-black hover:bg-yellow-300 transition disabled:opacity-60"
          >
            {loading ? "Signing in..." : "Sign in"}
          </button>

          <div className="text-xs text-blue-800">
            No sign-up. Accounts are created by an administrator.
          </div>
        </form>
      </div>
    </main>
  );
}