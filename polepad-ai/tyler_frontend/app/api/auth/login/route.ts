import { NextResponse } from "next/server";
import { getUser } from "@/lib/users";
import { makeSessionCookieValue, SESSION_COOKIE_NAME } from "@/lib/auth";

export async function POST(req: Request) {
  try {
    const body = await req.json().catch(() => null);
    if (!body?.username || !body?.password) {
      return NextResponse.json({ ok: false, error: "Missing username/password" }, { status: 400 });
    }

    const { username, password } = body;

    const user = await getUser(username);

    if (!user || user.password !== password) {
      return NextResponse.json({ ok: false, error: "Invalid credentials" }, { status: 401 });
    }

    const cookieValue = makeSessionCookieValue(user.username);
    const res = NextResponse.json({ ok: true, role: user.role });

    res.cookies.set({
      name: SESSION_COOKIE_NAME,
      value: cookieValue,
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
    });

    return res;
  } catch (err: any) {
    console.error("LOGIN ERROR:", err);
    return NextResponse.json({ ok: false, error: err?.message || "Server error" }, { status: 500 });
  }
}