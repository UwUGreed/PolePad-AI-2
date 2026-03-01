// lib/types.ts
export type Role = "admin" | "user";

export type UserRecord = {
  username: string;
  password: string; // demo only (plaintext). Use hashing in real apps.
  role: Role;
};