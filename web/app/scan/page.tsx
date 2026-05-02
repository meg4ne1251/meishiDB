"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { cardsApi } from "@/lib/api";
import { CardImageCapture } from "@/components/card-image-capture";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function ScanPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!file) return;
    setError(null);
    setProgress("名刺を作成中...");
    try {
      const created = await cardsApi.create({ source: "camera" });
      setProgress("画像をアップロード & OCR 実行中...");
      const card = await cardsApi.uploadImage(created.id, file, {
        side: "front",
        runOcr: true,
        filename: file.name || "card.jpg",
      });
      router.replace(`/cards/${card.id}`);
    } catch (e) {
      setError("登録に失敗しました");
      setProgress(null);
    }
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">名刺をスキャン</h1>
        <p className="text-sm text-muted-foreground">
          カメラまたはファイルから取り込み、自動で OCR を実行します。
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>画像</CardTitle>
        </CardHeader>
        <CardContent>
          <CardImageCapture onPicked={(f) => setFile(f)} />
        </CardContent>
      </Card>

      {progress && <p className="text-sm text-muted-foreground">{progress}</p>}
      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => router.back()}>
          キャンセル
        </Button>
        <Button onClick={submit} disabled={!file || !!progress}>
          登録
        </Button>
      </div>
    </div>
  );
}
