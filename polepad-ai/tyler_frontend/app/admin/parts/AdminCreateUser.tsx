"use client";

import { useState } from "react";

export default function AdminCreateUser() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function createUser(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    setErr(null);
    setLoading(true);

    try {
      const res = await fetch("/api/admin/add-user", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      const data = await res.json().catch(() => null);

      if (!res.ok) {
        setErr(data?.error || "Failed to create user");
        return;
      }

      setMsg("User created.");
      setUsername("");
      setPassword("");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={createUser} className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="text-sm font-semibold text-blue-900">Username</label>
          <input
            className="mt-1 w-full rounded-xl border border-blue-200 bg-white px-3 py-2 text-blue-900 placeholder:text-blue-400 outline-none focus:ring-2 focus:ring-blue-600"
            placeholder="Enter username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>

        <div>
          <label className="text-sm font-semibold text-blue-900">Password</label>
          <input
            className="mt-1 w-full rounded-xl border border-blue-200 bg-white px-3 py-2 text-blue-900 placeholder:text-blue-400 outline-none focus:ring-2 focus:ring-blue-600"
            placeholder="Enter password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
      </div>

      {err && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      {msg && (
        <div className="rounded-xl border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
          {msg}
        </div>
      )}

      <button
        type="submit"
        disabled={loading}
        className="w-full rounded-xl bg-yellow-400 px-4 py-2 font-semibold text-black hover:bg-yellow-300 transition disabled:opacity-60"
      >
        {loading ? "Adding..." : "Add user"}
      </button>
    </form>
  );
}