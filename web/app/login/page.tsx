"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { KeyRound } from "lucide-react";

import { authApi, ApiError } from "@/lib/api";
import { loginWithPasskey } from "@/lib/webauthn";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

const schema = z.object({
  email: z.string().email("メールアドレスの形式が正しくありません"),
  password: z.string().min(1, "パスワードを入力してください"),
});

type FormValues = z.infer<typeof schema>;

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [passkeyBusy, setPasskeyBusy] = useState(false);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  async function onSubmit(values: FormValues) {
    setError(null);
    try {
      await authApi.login(values.email, values.password);
      router.replace("/cards");
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setError("メールアドレスまたはパスワードが違います");
      } else {
        setError("ログインに失敗しました");
      }
    }
  }

  async function passkeyLogin() {
    setError(null);
    setPasskeyBusy(true);
    try {
      const email = watch("email") || undefined;
      await loginWithPasskey(email);
      router.replace("/cards");
      router.refresh();
    } catch (e) {
      setError(
        e instanceof Error
          ? `パスキー認証に失敗しました: ${e.message}`
          : "パスキー認証に失敗しました",
      );
    } finally {
      setPasskeyBusy(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-6 py-10">
      <Card>
        <CardHeader>
          <CardTitle>ログイン</CardTitle>
          <CardDescription>パスキーまたはパスワードでサインインします。</CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit(onSubmit)}>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="email">メールアドレス</Label>
              <Input id="email" type="email" autoComplete="email" {...register("email")} />
              {errors.email && (
                <p className="text-xs text-destructive">{errors.email.message}</p>
              )}
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">パスワード</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                {...register("password")}
              />
              {errors.password && (
                <p className="text-xs text-destructive">{errors.password.message}</p>
              )}
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
          </CardContent>
          <CardFooter className="flex flex-col items-stretch gap-3">
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "サインイン中..." : "サインイン"}
            </Button>

            <div className="flex items-center gap-2">
              <Separator className="flex-1" />
              <span className="text-xs text-muted-foreground">または</span>
              <Separator className="flex-1" />
            </div>

            <Button
              type="button"
              variant="outline"
              onClick={passkeyLogin}
              disabled={passkeyBusy}
            >
              <KeyRound className="mr-2 h-4 w-4" />
              {passkeyBusy ? "認証中..." : "パスキーでログイン"}
            </Button>

            <p className="text-center text-sm text-muted-foreground">
              アカウントが無い場合は{" "}
              <Link className="underline" href="/register">
                新規登録
              </Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
