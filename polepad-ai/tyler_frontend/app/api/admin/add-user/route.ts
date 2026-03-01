import { NextResponse } from "next/server";
import { addUser } from "@/lib/users";
import { getSessionUser } from "@/lib/auth";

export async function POST(req: Request) {
  const session = await getSessionUser();

  if (!session || session.role !== "admin") {
    return NextResponse.json({ ok: false, error: "Forbidden" }, { status: 403 });
  }

  const { username, password } = await req.json();

  try {
    addUser(username, password);
    return NextResponse.json({ ok: true });
  } catch (e: any) {
    return NextResponse.json({ ok: false, error: e.message }, { status: 400 });
  }
}