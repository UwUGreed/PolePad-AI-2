// lib/users.ts
import "server-only";
import path from "path";
import { promises as fs } from "fs";
import type { UserRecord } from "./types";

const DATA_DIR = path.join(process.cwd(), "data");
const USERS_FILE = path.join(DATA_DIR, "users.json");

const ADMIN_USER: UserRecord = {
  username: "Admin",
  password: "Gridstorm",
  role: "admin",
};

async function fileExists(p: string) {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

async function ensureStorage() {
  await fs.mkdir(DATA_DIR, { recursive: true });

  const exists = await fileExists(USERS_FILE);
  if (!exists) {
    await fs.writeFile(USERS_FILE, JSON.stringify([ADMIN_USER], null, 2), "utf8");
  }
}

async function readUsersUnsafe(): Promise<UserRecord[]> {
  // assumes file exists
  const raw = await fs.readFile(USERS_FILE, "utf8");
  const parsed = JSON.parse(raw);
  return Array.isArray(parsed) ? (parsed as UserRecord[]) : [];
}

async function writeUsers(users: UserRecord[]) {
  await fs.writeFile(USERS_FILE, JSON.stringify(users, null, 2), "utf8");
}

async function readUsers(): Promise<UserRecord[]> {
  await ensureStorage();

  let users = await readUsersUnsafe();

  // ensure Admin exists (without recursion)
  const hasAdmin = users.some((u) => u.username === ADMIN_USER.username);
  if (!hasAdmin) {
    users = [...users, ADMIN_USER];
    await writeUsers(users);
  }

  return users;
}

export async function getUser(username: string): Promise<UserRecord | undefined> {
  const users = await readUsers();
  return users.find((u) => u.username === username);
}

export async function addUser(username: string, password: string): Promise<void> {
  if (!username || !password) throw new Error("Missing username/password");

  const users = await readUsers();
  if (users.some((u) => u.username === username)) {
    throw new Error("User already exists");
  }

  // ✅ force basic user role
  users.push({ username, password, role: "user" });
  await writeUsers(users);
}

export async function listUsers(): Promise<Array<Pick<UserRecord, "username" | "role">>> {
  const users = await readUsers();
  return users.map((u) => ({ username: u.username, role: u.role }));
}

export async function removeUser(username: string): Promise<void> {
  if (!username) throw new Error("Missing username");

  // Prevent deleting the main admin account
  if (username === "Admin") {
    throw new Error("Cannot remove Admin");
  }

  const users = await readUsers();
  const next = users.filter((u) => u.username !== username);

  if (next.length === users.length) {
    throw new Error("User not found");
  }

  await writeUsers(next);
}