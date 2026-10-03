import { redirect } from "next/navigation";
import { headers } from "next/headers";

import { authApi } from "@/lib/api";

export default async function HomePage() {
  const cookie = (await headers()).get("cookie") ?? "";
  let authenticated = false;
  try {
    if (cookie) {
      await authApi.me(cookie);
      authenticated = true;
    }
  } catch {
    // fallthrough → /login
  }
  redirect(authenticated ? "/cards" : "/login");
}
