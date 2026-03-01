import { getSessionUser } from "@/lib/auth";
import { redirect } from "next/navigation";

export default async function RequireAuth({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await getSessionUser();
  if (!user) redirect("/login");
  return <>{children}</>;
}