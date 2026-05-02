import { redirect } from "next/navigation";
import { headers } from "next/headers";

import { authApi } from "@/lib/api";

export default async function HomePage() {
  const cookie = (await headers()).get("cookie") ?? "";
  try {
    if (cookie) {
      await authApi.me(cookie);
      redirect("/cards");
    }
  } catch {
    // fallthrough → /login
  }
  redirect("/login");
}
