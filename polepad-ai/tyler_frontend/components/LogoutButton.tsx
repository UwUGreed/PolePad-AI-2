"use client";

import { useState } from "react";

export default function LogoutButton() {
  const [loading, setLoading] = useState(false);

  async function onLogout() {
    try {
      setLoading(true);
      await fetch("/api/logout", { method: "POST" });

      // Hard navigation guarantees header/layout re-renders everywhere
      window.location.href = "/login";
    } finally {
      setLoading(false);
    }
  }

  return (
    <button
      type="button"
      onClick={onLogout}
      disabled={loading}
      className="cursor-pointer rounded-2xl bg-yellow-400 px-8 py-4 text-lg font-bold text-black shadow-sm transition-all duration-150 hover:bg-yellow-300 hover:shadow-md active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
    >
      {loading ? "Logging out..." : "Logout"}
    </button>
  );
}