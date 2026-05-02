"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Camera, KeyRound, LogOut, ScanLine } from "lucide-react";

import { authApi } from "@/lib/api";
import type { CurrentUser } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";

export function Header({ user }: { user: CurrentUser | null }) {
  const router = useRouter();

  async function logout() {
    await authApi.logout().catch(() => undefined);
    router.replace("/login");
    router.refresh();
  }

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/80 backdrop-blur">
      <div className="container flex h-14 items-center justify-between gap-4">
        <Link href="/cards" className="flex items-center gap-2 font-semibold tracking-tight">
          <ScanLine className="h-5 w-5 text-primary" />
          meishiDB
        </Link>

        {user ? (
          <nav className="flex items-center gap-1 text-sm">
            <Link
              href="/cards"
              className="rounded-md px-3 py-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              名刺
            </Link>
            <Link
              href="/scan"
              className="hidden items-center rounded-md px-3 py-1.5 text-muted-foreground hover:bg-accent hover:text-foreground sm:inline-flex"
            >
              <Camera className="mr-1 h-3.5 w-3.5" />
              スキャン
            </Link>
            <Link
              href="/tags"
              className="rounded-md px-3 py-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              タグ
            </Link>
            <Link
              href="/settings/passkeys"
              className="hidden items-center rounded-md px-3 py-1.5 text-muted-foreground hover:bg-accent hover:text-foreground sm:inline-flex"
              aria-label="passkeys"
            >
              <KeyRound className="h-3.5 w-3.5" />
            </Link>
            <span className="ml-2 hidden text-xs text-muted-foreground sm:inline">
              {user.display_name}
            </span>
            <ThemeToggle />
            <Button size="icon" variant="ghost" onClick={logout} aria-label="logout">
              <LogOut className="h-4 w-4" />
            </Button>
          </nav>
        ) : (
          <ThemeToggle />
        )}
      </div>
    </header>
  );
}
