"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Camera, Download, Heart, Plus, Search, Star, Tags as TagsIcon } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { cardsApi, exportApi, tagsApi, type ListCardsParams } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function useDebounced<T>(value: T, delay = 200) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

export default function CardsPage() {
  const router = useRouter();
  const params = useSearchParams();

  const initialScope = (params.get("scope") as ListCardsParams["scope"]) ?? "owned";
  const [scope, setScope] = useState<NonNullable<ListCardsParams["scope"]>>(initialScope);
  const [favorite, setFavorite] = useState(params.get("favorite") === "1");
  const [tagId, setTagId] = useState<string | null>(params.get("tag") || null);
  const [query, setQuery] = useState(params.get("q") ?? "");
  const debouncedQ = useDebounced(query);

  const queryParams: ListCardsParams = useMemo(
    () => ({
      scope,
      q: debouncedQ || undefined,
      favorite: favorite || undefined,
      tag_id: tagId || undefined,
    }),
    [scope, debouncedQ, favorite, tagId],
  );

  const { data, isLoading } = useQuery({
    queryKey: ["cards", queryParams],
    queryFn: () => cardsApi.list(queryParams),
  });
  const tagsQuery = useQuery({ queryKey: ["tags"], queryFn: () => tagsApi.list() });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">名刺</h1>
          <p className="text-sm text-muted-foreground">
            {data ? `${data.total} 件` : "読み込み中..."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <a
              href={exportApi.url({
                format: "csv",
                scope,
                q: debouncedQ || undefined,
                favorite: favorite || undefined,
                tag_id: tagId || undefined,
              })}
            >
              <Download className="mr-1 h-3.5 w-3.5" /> CSV
            </a>
          </Button>
          <Button asChild variant="outline" size="sm">
            <a
              href={exportApi.url({
                format: "vcard",
                scope,
                q: debouncedQ || undefined,
                favorite: favorite || undefined,
                tag_id: tagId || undefined,
              })}
            >
              <Download className="mr-1 h-3.5 w-3.5" /> vCard
            </a>
          </Button>
          <Button asChild variant="outline">
            <Link href="/scan">
              <Camera className="mr-1 h-4 w-4" /> スキャン
            </Link>
          </Button>
          <Button asChild>
            <Link href="/cards/new">
              <Plus className="mr-1 h-4 w-4" /> 新規作成
            </Link>
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="氏名・会社・メール・電話番号..."
            className="pl-9"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
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

          <Button
            size="sm"
            variant={favorite ? "default" : "outline"}
            onClick={() => setFavorite((f) => !f)}
          >
            <Star className="mr-1 h-3.5 w-3.5" /> お気に入り
          </Button>
        </div>
      </div>

      {tagsQuery.data && tagsQuery.data.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <TagsIcon className="h-4 w-4 text-muted-foreground" />
          <Button
            size="sm"
            variant={tagId === null ? "secondary" : "ghost"}
            onClick={() => setTagId(null)}
          >
            全て
          </Button>
          {tagsQuery.data.map((t) => (
            <Button
              key={t.id}
              size="sm"
              variant={tagId === t.id ? "secondary" : "ghost"}
              onClick={() => setTagId(t.id)}
            >
              {t.name}
            </Button>
          ))}
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-muted-foreground">読み込み中...</p>
      ) : data?.items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-12 text-center text-muted-foreground">
          該当する名刺がありません
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data?.items.map((c) => {
            const f = c.fields;
            return (
              <Link
                key={c.id}
                href={`/cards/${c.id}`}
                className="group flex flex-col gap-2 rounded-lg border border-border bg-card p-4 transition hover:border-foreground/30"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-base font-semibold">
                      {f?.person_name || "(無題)"}
                    </p>
                    <p className="truncate text-sm text-muted-foreground">
                      {f?.company || "—"}
                      {f?.department ? ` / ${f.department}` : ""}
                    </p>
                  </div>
                  {c.is_favorite && (
                    <Heart className="h-4 w-4 fill-rose-500 text-rose-500" />
                  )}
                </div>

                <div className="flex flex-col gap-0.5 text-xs text-muted-foreground">
                  {f?.title && <span>{f.title}</span>}
                  {f?.email && <span className="truncate">{f.email}</span>}
                  {f?.phone && <span>{f.phone}</span>}
                </div>

                {(c.tags.length > 0 || c.shared) && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {c.shared && <Badge variant="outline">共有</Badge>}
                    {c.tags.map((t) => (
                      <Badge key={t.id} variant="secondary">
                        {t.name}
                      </Badge>
                    ))}
                  </div>
                )}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
