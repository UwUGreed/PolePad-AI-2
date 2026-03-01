import { NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth";
import { removeUser } from "@/lib/users";

export async function POST(req: Request) {
  const session = await getSessionUser();

  // ✅ only admin can remove users
  if (!session || session.role !== "admin") {
    return NextResponse.json({ ok: false, error: "Forbidden" }, { status: 403 });
  }

  const body = await req.json().catch(() => null);
  const username = body?.username;

  try {
    await removeUser(username);
    return NextResponse.json({ ok: true });
  } catch (e: any) {
    return NextResponse.json({ ok: false, error: e.message }, { status: 400 });
  }
}