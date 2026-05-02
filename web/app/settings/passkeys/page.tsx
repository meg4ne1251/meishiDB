"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { webauthnApi } from "@/lib/api";
import { registerPasskey } from "@/lib/webauthn";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function PasskeysPage() {
  const qc = useQueryClient();
  const [nickname, setNickname] = useState("");
  const [error, setError] = useState<string | null>(null);

  const { data: creds } = useQuery({
    queryKey: ["passkeys"],
    queryFn: () => webauthnApi.list(),
  });

  const register = useMutation({
    mutationFn: () => registerPasskey(nickname || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["passkeys"] });
      setNickname("");
      setError(null);
    },
    onError: (e: unknown) =>
      setError(e instanceof Error ? e.message : "登録に失敗しました"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => webauthnApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["passkeys"] }),
  });

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">パスキー</h1>
        <p className="text-sm text-muted-foreground">
          端末の生体認証 / セキュリティキーでログインできます。
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>新しいパスキーを登録</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1 flex flex-col gap-1.5">
              <Label htmlFor="passkey-nickname">名前（任意）</Label>
              <Input
                id="passkey-nickname"
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                placeholder="iPhone / YubiKey など"
              />
            </div>
            <Button onClick={() => register.mutate()} disabled={register.isPending}>
              {register.isPending ? "登録中..." : "登録"}
            </Button>
          </div>
          {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

      <div className="flex flex-col gap-2">
        {creds?.length === 0 && (
          <p className="text-sm text-muted-foreground">登録済みパスキーはありません。</p>
        )}
        {creds?.map((c) => (
          <div
            key={c.id}
            className="flex items-center justify-between rounded-md border border-border bg-card px-4 py-2"
          >
            <div className="flex flex-col">
              <span className="text-sm font-medium">{c.nickname || "(無題)"}</span>
              <span className="text-xs text-muted-foreground">
                登録: {new Date(c.created_at).toLocaleString()}
                {c.last_used_at ? ` / 最終使用: ${new Date(c.last_used_at).toLocaleString()}` : ""}
              </span>
            </div>
            <Button
              size="icon"
              variant="ghost"
              aria-label="delete"
              onClick={() => {
                if (confirm("このパスキーを削除します。")) remove.mutate(c.id);
              }}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}
