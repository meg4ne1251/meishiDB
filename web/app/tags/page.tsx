"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";

import { tagsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function TagsPage() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [color, setColor] = useState("");
  const [error, setError] = useState<string | null>(null);

  const { data: tags } = useQuery({ queryKey: ["tags"], queryFn: () => tagsApi.list() });

  const createMutation = useMutation({
    mutationFn: () => tagsApi.create({ name, color: color || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tags"] });
      setName("");
      setColor("");
      setError(null);
    },
    onError: () => setError("タグ名が既に使われている可能性があります"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => tagsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tags"] }),
  });

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">タグ</h1>
        <p className="text-sm text-muted-foreground">名刺の分類用ラベル。所有者のみ管理できます。</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>新規タグ</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1 flex flex-col gap-1.5">
              <Label htmlFor="tag-name">名前</Label>
              <Input
                id="tag-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="顧客 / 取引先 / イベント など"
              />
            </div>
            <div className="flex flex-col gap-1.5 sm:w-32">
              <Label htmlFor="tag-color">色</Label>
              <Input
                id="tag-color"
                value={color}
                onChange={(e) => setColor(e.target.value)}
                placeholder="#22c55e"
              />
            </div>
            <Button
              onClick={() => createMutation.mutate()}
              disabled={!name || createMutation.isPending}
            >
              追加
            </Button>
          </div>
          {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

      <div className="flex flex-col gap-2">
        {tags?.length === 0 && (
          <p className="text-sm text-muted-foreground">タグはまだありません。</p>
        )}
        {tags?.map((t) => (
          <div
            key={t.id}
            className="flex items-center justify-between rounded-md border border-border bg-card px-4 py-2"
          >
            <div className="flex items-center gap-3">
              {t.color && (
                <span
                  className="h-3 w-3 rounded-full"
                  style={{ backgroundColor: t.color }}
                  aria-hidden
                />
              )}
              <span className="text-sm font-medium">{t.name}</span>
            </div>
            <Button
              size="icon"
              variant="ghost"
              aria-label="delete"
              onClick={() => {
                if (confirm("タグを削除します。名刺との紐付けも解除されます。")) {
                  deleteMutation.mutate(t.id);
                }
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
