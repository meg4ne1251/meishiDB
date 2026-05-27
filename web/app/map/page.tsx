"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { MapPin } from "lucide-react";

import { cardsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";

// maplibre-gl は window 前提なので SSR を無効化して読み込む
const MapView = dynamic(() => import("@/components/map-view").then((m) => m.MapView), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center text-sm text-muted-foreground">
      地図を読み込み中...
    </div>
  ),
});

type Scope = "owned" | "shared" | "all";

export default function MapPage() {
  const [scope, setScope] = useState<Scope>("owned");

  const { data, isLoading } = useQuery({
    queryKey: ["cards", "geo", scope],
    queryFn: () => cardsApi.geo(scope),
  });

  const points = data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <MapPin className="h-5 w-5 text-primary" />
            地図
          </h1>
          <p className="text-sm text-muted-foreground">
            {isLoading
              ? "読み込み中..."
              : `${points.length} 件の名刺を地図上に表示`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {(["owned", "shared", "all"] as const).map((s) => (
            <Button
              key={s}
              size="sm"
              variant={scope === s ? "default" : "outline"}
              onClick={() => setScope(s)}
            >
              {s === "owned" ? "自分" : s === "shared" ? "共有された" : "全て"}
            </Button>
          ))}
        </div>
      </div>

      <div className="relative h-[calc(100dvh-16rem)] min-h-[420px] overflow-hidden rounded-lg border border-border">
        <MapView points={points} />
        {!isLoading && points.length === 0 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div className="pointer-events-auto max-w-sm rounded-lg border border-border bg-card/95 p-6 text-center text-sm text-muted-foreground shadow-lg">
              位置情報を持つ名刺がまだありません。
              <br />
              名刺に住所を登録し、ジオコーダ（自前 Nominatim 等）を有効にすると
              ここに表示されます。
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
