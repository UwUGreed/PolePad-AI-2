// lib/auth.ts
import "server-only";

import { createHmac } from "crypto";
import { cookies } from "next/headers";
import { getUser } from "./users";
import type { Role } from "./types";

const COOKIE_NAME = "portal_session";

export type SessionUser = {
  username: string;
  role: Role;
};

function hmac(data: string, secret: string) {
  return createHmac("sha256", secret).update(data).digest("hex");
}

export function makeSessionCookieValue(username: string) {
  const secret = process.env.SESSION_SECRET || "";
  if (!secret) throw new Error("SESSION_SECRET not set");

  const payload = JSON.stringify({ username, iat: Date.now() });
  const sig = hmac(payload, secret);
  const b64 = Buffer.from(payload).toString("base64url");

  return `${b64}.${sig}`;
}

export async function getSessionUser(): Promise<SessionUser | null> {
  const secret = process.env.SESSION_SECRET || "";
  if (!secret) return null;

  // ✅ important for your environment
  const cookieStore = await cookies();
  const value = cookieStore.get(COOKIE_NAME)?.value;
  if (!value) return null;

  const [b64, sig] = value.split(".");
  if (!b64 || !sig) return null;

  const payload = Buffer.from(b64, "base64url").toString("utf8");
  const expected = hmac(payload, secret);
  if (expected !== sig) return null;

  const parsed = JSON.parse(payload) as { username: string };
  const user = await getUser(parsed.username); // ✅ getUser is async now

  return user ? { username: user.username, role: user.role } : null;
}

export const SESSION_COOKIE_NAME = COOKIE_NAME;