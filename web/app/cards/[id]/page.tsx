"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Heart, MapPin, RefreshCw, Share2, Trash2 } from "lucide-react";

import { cardsApi, tagsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CardImageCapture } from "@/components/card-image-capture";
import { CardMemos } from "@/components/card-memos";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

const schema = z.object({
  person_name: z.string().optional(),
  person_name_kana: z.string().optional(),
  company: z.string().optional(),
  department: z.string().optional(),
  title: z.string().optional(),
  postal_code: z.string().optional(),
  address: z.string().optional(),
  phone: z.string().optional(),
  mobile: z.string().optional(),
  fax: z.string().optional(),
  email: z.string().optional(),
  website: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

const FIELDS: Array<{ name: keyof FormValues; label: string; col?: 1 | 2 }> = [
  { name: "person_name", label: "氏名" },
  { name: "person_name_kana", label: "ふりがな" },
  { name: "company", label: "会社", col: 2 },
  { name: "department", label: "部署" },
  { name: "title", label: "役職" },
  { name: "email", label: "メール", col: 2 },
  { name: "phone", label: "電話" },
  { name: "mobile", label: "携帯" },
  { name: "fax", label: "FAX" },
  { name: "website", label: "Web" },
  { name: "postal_code", label: "郵便番号" },
  { name: "address", label: "住所", col: 2 },
];

export default function CardDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const cardId = params.id;

  const { data: card, isLoading } = useQuery({
    queryKey: ["card", cardId],
    queryFn: () => cardsApi.get(cardId),
  });
  const tagsQuery = useQuery({ queryKey: ["tags"], queryFn: () => tagsApi.list() });
  const sharesQuery = useQuery({
    queryKey: ["card", cardId, "shares"],
    queryFn: () => cardsApi.listShares(cardId),
    enabled: !!card && !card.shared,
  });

  const form = useForm<FormValues>({ resolver: zodResolver(schema) });
  const [tagSelection, setTagSelection] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!card) return;
    form.reset({
      person_name: card.fields?.person_name ?? "",
      person_name_kana: card.fields?.person_name_kana ?? "",
      company: card.fields?.company ?? "",
      department: card.fields?.department ?? "",
      title: card.fields?.title ?? "",
      postal_code: card.fields?.postal_code ?? "",
      address: card.fields?.address ?? "",
      phone: card.fields?.phone ?? "",
      mobile: card.fields?.mobile ?? "",
      fax: card.fields?.fax ?? "",
      email: card.fields?.email ?? "",
      website: card.fields?.website ?? "",
    });
    setTagSelection(new Set(card.tags.map((t) => t.id)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card?.id]);

  const updateMutation = useMutation({
    mutationFn: (values: FormValues) =>
      cardsApi.update(cardId, {
        fields: values,
        tag_ids: card?.shared ? undefined : Array.from(tagSelection),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["card", cardId] });
      qc.invalidateQueries({ queryKey: ["cards"] });
    },
  });

  const favMutation = useMutation({
    mutationFn: (on: boolean) => cardsApi.favorite(cardId, on),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["card", cardId] }),
  });

  const deleteMutation = useMutation({
    mutationFn: () => cardsApi.remove(cardId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cards"] });
      router.replace("/cards");
    },
  });

  const uploadFront = useMutation({
    mutationFn: (file: File) =>
      cardsApi.uploadImage(cardId, file, { side: "front", runOcr: true, filename: file.name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["card", cardId] }),
  });
  const uploadBack = useMutation({
    mutationFn: (file: File) =>
      cardsApi.uploadImage(cardId, file, { side: "back", runOcr: false, filename: file.name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["card", cardId] }),
  });
  const rerunOcr = useMutation({
    mutationFn: () => cardsApi.rerunOcr(cardId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["card", cardId] }),
  });
  const geocode = useMutation({
    mutationFn: () => cardsApi.geocode(cardId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["card", cardId] });
      qc.invalidateQueries({ queryKey: ["cards", "geo"] });
    },
  });

  if (isLoading) return <p className="text-sm text-muted-foreground">読み込み中...</p>;
  if (!card) return <p className="text-sm">名刺が見つかりません</p>;

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {card.fields?.person_name || "(無題)"}
          </h1>
          <p className="text-sm text-muted-foreground">
            {card.fields?.company ?? "—"}
            {card.fields?.title ? ` ・ ${card.fields.title}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {card.shared && <Badge variant="outline">共有</Badge>}
          <Badge variant="secondary">{card.status}</Badge>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => favMutation.mutate(!card.is_favorite)}
            aria-label="favorite"
          >
            <Heart
              className={`h-4 w-4 ${card.is_favorite ? "fill-rose-500 text-rose-500" : ""}`}
            />
          </Button>

          {!card.shared && <ShareDialog cardId={cardId} />}

          {!card.shared && (
            <Button
              size="icon"
              variant="ghost"
              onClick={() => {
                if (confirm("この名刺を削除します。よろしいですか？")) deleteMutation.mutate();
              }}
              aria-label="delete"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      {!card.shared && (
        <Card>
          <CardHeader>
            <CardTitle>画像</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <span className="text-xs text-muted-foreground">表面</span>
                {card.image_front_key ? (
                  <a
                    href={cardsApi.imageUrl(cardId, "front")}
                    target="_blank"
                    rel="noreferrer"
                    className="block overflow-hidden rounded-md border border-border"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={cardsApi.imageUrl(cardId, "front", true)}
                      alt="front"
                      className="max-h-48 w-full object-contain bg-black/40"
                    />
                  </a>
                ) : (
                  <p className="text-xs text-muted-foreground">未アップロード</p>
                )}
                <CardImageCapture
                  label="表面を撮影"
                  disabled={uploadFront.isPending}
                  onPicked={(f) => uploadFront.mutate(f)}
                />
              </div>
              <div className="flex flex-col gap-2">
                <span className="text-xs text-muted-foreground">裏面</span>
                {card.image_back_key ? (
                  <a
                    href={cardsApi.imageUrl(cardId, "back")}
                    target="_blank"
                    rel="noreferrer"
                    className="block overflow-hidden rounded-md border border-border"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={cardsApi.imageUrl(cardId, "back")}
                      alt="back"
                      className="max-h-48 w-full object-contain bg-black/40"
                    />
                  </a>
                ) : (
                  <p className="text-xs text-muted-foreground">未アップロード</p>
                )}
                <CardImageCapture
                  label="裏面を撮影"
                  disabled={uploadBack.isPending}
                  onPicked={(f) => uploadBack.mutate(f)}
                />
              </div>
            </div>

            {card.image_front_key && (
              <div className="flex flex-wrap items-center justify-between gap-2 pt-2 text-xs text-muted-foreground">
                <span>
                  ステータス: {card.status}
                  {uploadFront.isPending && " （アップロード中...）"}
                  {rerunOcr.isPending && " （OCR 実行中...）"}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => rerunOcr.mutate()}
                  disabled={rerunOcr.isPending}
                >
                  <RefreshCw className="mr-1 h-3.5 w-3.5" />
                  OCR を再実行
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <form
        onSubmit={form.handleSubmit((v) => updateMutation.mutate(v))}
        className="flex flex-col gap-6"
      >
        <Card>
          <CardHeader>
            <CardTitle>項目</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 sm:grid-cols-2">
              {FIELDS.map((f) => (
                <div
                  key={f.name}
                  className={`flex flex-col gap-1.5 ${f.col === 2 ? "sm:col-span-2" : ""}`}
                >
                  <Label htmlFor={f.name}>{f.label}</Label>
                  <Input id={f.name} {...form.register(f.name)} />
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>位置情報</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm text-muted-foreground">
              {card.fields?.latitude != null && card.fields?.longitude != null ? (
                <span className="font-mono text-xs">
                  {card.fields.latitude.toFixed(5)}, {card.fields.longitude.toFixed(5)}
                </span>
              ) : (
                "座標は未取得です"
              )}
            </div>
            <div className="flex items-center gap-2">
              {card.fields?.latitude != null && (
                <Button asChild type="button" size="sm" variant="ghost">
                  <Link href="/map">
                    <MapPin className="mr-1 h-3.5 w-3.5" /> 地図で見る
                  </Link>
                </Button>
              )}
              {!card.shared && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={geocode.isPending || !card.fields?.address}
                  onClick={() => geocode.mutate()}
                >
                  <MapPin className="mr-1 h-3.5 w-3.5" />
                  {geocode.isPending
                    ? "取得中..."
                    : card.fields?.latitude != null
                      ? "座標を再取得"
                      : "座標を取得"}
                </Button>
              )}
            </div>
            {geocode.isError && (
              <p className="w-full text-xs text-destructive">
                座標を取得できませんでした（住所が不正か、ジオコーダが無効の可能性があります）。
              </p>
            )}
          </CardContent>
        </Card>

        {!card.shared && tagsQuery.data && (
          <Card>
            <CardHeader>
              <CardTitle>タグ</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {tagsQuery.data.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    タグがありません。タグ管理から追加できます。
                  </p>
                )}
                {tagsQuery.data.map((t) => {
                  const on = tagSelection.has(t.id);
                  return (
                    <Button
                      key={t.id}
                      type="button"
                      size="sm"
                      variant={on ? "default" : "outline"}
                      onClick={() =>
                        setTagSelection((prev) => {
                          const next = new Set(prev);
                          if (on) next.delete(t.id);
                          else next.add(t.id);
                          return next;
                        })
                      }
                    >
                      {t.name}
                    </Button>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {!card.shared && sharesQuery.data && sharesQuery.data.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>共有中</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="flex flex-col gap-1.5 text-sm">
                {sharesQuery.data.map((s) => (
                  <li key={s.id} className="flex items-center justify-between">
                    <span className="font-mono text-xs text-muted-foreground">
                      {s.shared_with}
                    </span>
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary">{s.permission}</Badge>
                      <Button
                        size="sm"
                        variant="ghost"
                        type="button"
                        onClick={async () => {
                          await cardsApi.unshare(cardId, s.id);
                          qc.invalidateQueries({ queryKey: ["card", cardId, "shares"] });
                        }}
                      >
                        解除
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        <div className="flex justify-end gap-2">
          <Button type="submit" disabled={updateMutation.isPending}>
            {updateMutation.isPending ? "保存中..." : "保存"}
          </Button>
        </div>
      </form>
      <CardMemos key={cardId} cardId={cardId} />
    </div>
  );
}

function ShareDialog({ cardId }: { cardId: string }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [permission, setPermission] = useState<"view" | "edit">("view");
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setError(null);
    try {
      await cardsApi.share(cardId, { user_email: email, permission });
      qc.invalidateQueries({ queryKey: ["card", cardId, "shares"] });
      setEmail("");
      setOpen(false);
    } catch {
      setError("共有に失敗しました（ユーザーが見つからない可能性があります）");
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="icon" variant="ghost" aria-label="share">
          <Share2 className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>名刺を共有</DialogTitle>
          <DialogDescription>
            共有先ユーザーのメールアドレスを入力してください。
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="share-email">メールアドレス</Label>
            <Input
              id="share-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@example.com"
            />
          </div>
          <div className="flex gap-2">
            {(["view", "edit"] as const).map((p) => (
              <Button
                key={p}
                size="sm"
                type="button"
                variant={permission === p ? "default" : "outline"}
                onClick={() => setPermission(p)}
              >
                {p === "view" ? "閲覧のみ" : "編集可"}
              </Button>
            ))}
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
            キャンセル
          </Button>
          <Button type="button" onClick={submit} disabled={!email}>
            共有
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
