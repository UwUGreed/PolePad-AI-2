import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { SESSION_COOKIE_NAME } from "@/lib/auth";

export async function POST() {
  const store = await cookies();

  // Prefer delete if available (Next supports it)
  store.delete(SESSION_COOKIE_NAME);

  // Extra safety: also set expired cookie (covers edge cases / older runtimes)
  store.set(SESSION_COOKIE_NAME, "", {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    expires: new Date(0),
    maxAge: 0,
  });

  return NextResponse.json({ ok: true });
}