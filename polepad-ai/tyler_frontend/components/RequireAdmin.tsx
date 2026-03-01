import { getSessionUser } from "@/lib/auth";
import { redirect } from "next/navigation";

export default async function RequireAdmin({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await getSessionUser();

  if (!user) redirect("/login");
  if (user.role !== "admin") redirect("/portal");

  return <>{children}</>;
}