"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useQuery } from "@tanstack/react-query";

import { cardsApi, tagsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

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
  { name: "person_name", label: "氏名", col: 1 },
  { name: "person_name_kana", label: "ふりがな", col: 1 },
  { name: "company", label: "会社", col: 2 },
  { name: "department", label: "部署", col: 1 },
  { name: "title", label: "役職", col: 1 },
  { name: "email", label: "メール", col: 2 },
  { name: "phone", label: "電話", col: 1 },
  { name: "mobile", label: "携帯", col: 1 },
  { name: "fax", label: "FAX", col: 1 },
  { name: "website", label: "Web", col: 1 },
  { name: "postal_code", label: "郵便番号", col: 1 },
  { name: "address", label: "住所", col: 2 },
];

export default function NewCardPage() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set());

  const tagsQuery = useQuery({ queryKey: ["tags"], queryFn: () => tagsApi.list() });
  const { register, handleSubmit } = useForm<FormValues>({
    resolver: zodResolver(schema),
  });

  async function onSubmit(values: FormValues) {
    setError(null);
    setSubmitting(true);
    try {
      const card = await cardsApi.create({
        source: "manual",
        fields: values,
        tag_ids: Array.from(selectedTags),
      });
      router.replace(`/cards/${card.id}`);
    } catch (e) {
      setError("作成に失敗しました");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">名刺を作成</h1>
        <p className="text-sm text-muted-foreground">
          手入力で登録します。画像から自動取り込みする場合は{" "}
          <a className="underline" href="/scan">スキャン</a> を利用してください。
        </p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-6">
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
                  <Input id={f.name} {...register(f.name)} />
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {tagsQuery.data && tagsQuery.data.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>タグ</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {tagsQuery.data.map((t) => {
                  const on = selectedTags.has(t.id);
                  return (
                    <Button
                      key={t.id}
                      type="button"
                      size="sm"
                      variant={on ? "default" : "outline"}
                      onClick={() =>
                        setSelectedTags((prev) => {
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

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => router.back()}>
            キャンセル
          </Button>
          <Button type="submit" disabled={submitting}>
            {submitting ? "作成中..." : "作成"}
          </Button>
        </div>
      </form>
    </div>
  );
}
