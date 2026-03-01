// app/api/admin/users/route.ts

import { NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth";
import { listUsers } from "@/lib/users";

export async function GET() {
  const session = await getSessionUser();

  if (!session) {
    return NextResponse.json(
      { ok: false, error: "Unauthorized" },
      { status: 401 }
    );
  }

  const users = await listUsers();

  return NextResponse.json({
    ok: true,
    users,
  });
}