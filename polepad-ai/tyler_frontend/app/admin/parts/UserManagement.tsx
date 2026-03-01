"use client";

import { useEffect, useState } from "react";

type UserRow = { username: string; role: "admin" | "user" };

export default function UserManagement({ isAdmin }: { isAdmin: boolean }) {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function load() {
    setErr(null);
    setMsg(null);
    setLoading(true);

    const res = await fetch("/api/admin/users", { method: "GET" });
    const data = await res.json().catch(() => null);

    if (!res.ok) {
      setErr(data?.error || "Failed to load users");
      setLoading(false);
      return;
    }

    setUsers(data?.users || []);
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, []);

  async function onRemove(username: string) {
    setErr(null);
    setMsg(null);

    const res = await fetch("/api/admin/remove-user", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username }),
    });

    const data = await res.json().catch(() => null);

    if (!res.ok) {
      setErr(data?.error || "Failed to remove user");
      return;
    }

    setMsg(`Removed ${username}`);
    await load();
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-blue-800">
          Total users:{" "}
          <span className="font-semibold text-blue-900">{users.length}</span>
        </div>

        <button
          type="button"
          onClick={load}
          className="inline-flex items-center justify-center rounded-xl border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-900 hover:bg-blue-100 transition"
        >
          Refresh
        </button>
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

      <div className="overflow-x-auto rounded-2xl border border-blue-200">
        <table className="w-full border-collapse">
          <thead className="bg-blue-50">
            <tr className="text-left text-sm text-blue-900">
              <th className="px-4 py-3 font-semibold">Username</th>
              <th className="px-4 py-3 font-semibold">Role</th>
              <th className="px-4 py-3 font-semibold text-right">Actions</th>
            </tr>
          </thead>

          <tbody>
            {users.map((u) => (
              <tr key={u.username} className="border-t border-blue-100 text-sm">
                <td className="px-4 py-3 text-blue-900">{u.username}</td>

                <td className="px-4 py-3">
                  <span className="inline-flex rounded-full border border-blue-200 bg-white px-3 py-1 text-xs font-semibold text-blue-900">
                    {u.role}
                  </span>
                </td>

                <td className="px-4 py-3 text-right">
                  {isAdmin && u.username !== "Admin" ? (
                    <button
                      onClick={() => onRemove(u.username)}
                      className="rounded-lg border border-red-300 bg-red-50 px-3 py-1 text-sm font-semibold text-red-700 hover:bg-red-100"
                    >
                      Remove
                    </button>
                  ) : (
                    <span className="text-blue-700">—</span>
                  )}
                </td>
              </tr>
            ))}

            {users.length === 0 && (
              <tr>
                <td className="px-4 py-6 text-blue-800" colSpan={3}>
                  No users found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}