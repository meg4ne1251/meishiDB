import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";

import { Providers } from "@/components/providers";
import { Header } from "@/components/header";
import { ServiceWorkerRegister } from "@/components/sw-register";
import { authApi } from "@/lib/api";
import type { CurrentUser } from "@/lib/types";

import "./globals.css";

export const metadata: Metadata = {
  title: "meishiDB",
  description: "セルフホスト名刺管理",
  manifest: "/manifest.webmanifest",
  applicationName: "meishiDB",
  appleWebApp: {
    capable: true,
    title: "meishiDB",
    statusBarStyle: "black-translucent",
  },
  icons: {
    icon: "/icon.svg",
    apple: "/icon.svg",
  },
};

export const viewport: Viewport = {
  themeColor: "#0a0a0a",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

async function getMe(): Promise<CurrentUser | null> {
  const cookie = (await headers()).get("cookie") ?? "";
  if (!cookie) return null;
  try {
    return await authApi.me(cookie);
  } catch {
    return null;
  }
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const user = await getMe();
  return (
    <html lang="ja" suppressHydrationWarning>
      <body className="min-h-dvh font-sans antialiased">
        <Providers userId={user?.id ?? null}>
          <Header user={user} />
          <main className="container py-8">{children}</main>
          <ServiceWorkerRegister />
        </Providers>
      </body>
    </html>
  );
}
