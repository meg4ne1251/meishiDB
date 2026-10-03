"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, cardsApi } from "@/lib/api";
import type { CardMemo } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

const MAX_MEMO_LENGTH = 5000;

function errorMessage(error: Error) {
  if (error instanceof ApiError && (error.status === 403 || error.status === 404)) {
    return "操作する権限がありません。画面を再読み込みして確認してください。";
  }
  return "メモを保存・削除できませんでした。時間をおいて再度お試しください。";
}

export function CardMemos({ cardId }: { cardId: string }) {
  const qc = useQueryClient();
  const [body, setBody] = useState("");
  const queryKey = ["card", cardId, "memos"];
  const memos = useQuery({ queryKey, queryFn: () => cardsApi.listMemos(cardId) });
  const refresh = () => qc.invalidateQueries({ queryKey });
  const create = useMutation({
    mutationFn: () => cardsApi.createMemo(cardId, body.trim()),
    onSuccess: async () => {
      setBody("");
      await refresh();
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>メモ</CardTitle>
        <p className="text-xs text-muted-foreground">この名刺の共有先もメモを閲覧できます。</p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {memos.isPending && <p className="text-sm text-muted-foreground">読み込み中...</p>}
        {memos.isError && (
          <div role="alert" className="flex items-center gap-2 text-sm text-destructive">
            <p>メモを読み込めませんでした。</p>
            <Button type="button" size="sm" variant="outline" onClick={() => memos.refetch()}>
              再試行
            </Button>
          </div>
        )}
        {!memos.isError && memos.data && (
          <>
            {memos.data.can_create ? (
              <form
                className="flex flex-col gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (body.trim() && !create.isPending) create.mutate();
                }}
              >
                <Label htmlFor="new-memo">メモを追加</Label>
                <Textarea
                  id="new-memo"
                  value={body}
                  onChange={(event) => {
                    setBody(event.target.value);
                    create.reset();
                  }}
                  placeholder="名刺交換のきっかけや、次回の連絡事項など"
                  maxLength={MAX_MEMO_LENGTH}
                  rows={4}
                  disabled={create.isPending}
                  required
                  aria-describedby="new-memo-count"
                />
                <div className="flex items-center justify-between gap-2">
                  <span id="new-memo-count" className="text-xs text-muted-foreground">
                    {body.length} / {MAX_MEMO_LENGTH}文字
                  </span>
                  <Button type="submit" size="sm" disabled={!body.trim() || create.isPending}>
                    {create.isPending ? "追加中..." : "追加"}
                  </Button>
                </div>
                {create.error && (
                  <p role="alert" className="text-sm text-destructive">
                    {errorMessage(create.error)}
                  </p>
                )}
              </form>
            ) : (
              <p className="text-xs text-muted-foreground">
                閲覧権限で共有されています。メモの追加・編集はできません。
              </p>
            )}
            {memos.data.items.length === 0 ? (
              <p className="text-sm text-muted-foreground">メモはまだありません。</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {memos.data.items.map((memo) => (
                  <MemoItem key={memo.id} cardId={cardId} memo={memo} onChanged={refresh} />
                ))}
              </ul>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function MemoItem({ cardId, memo, onChanged }: {
  cardId: string;
  memo: CardMemo;
  onChanged: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(memo.body);
  const update = useMutation({
    mutationFn: () => cardsApi.updateMemo(cardId, memo.id, body.trim()),
    onSuccess: async () => {
      setEditing(false);
      await onChanged();
    },
  });
  const remove = useMutation({
    mutationFn: () => cardsApi.deleteMemo(cardId, memo.id),
    onSuccess: onChanged,
  });
  const pending = update.isPending || remove.isPending;
  const error = update.error || remove.error;

  return (
    <li className="min-w-0 rounded-md border border-border p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="break-words text-xs text-muted-foreground">
          {memo.author_name} ・{" "}
          <time dateTime={memo.created_at}>
            {new Date(memo.created_at).toLocaleString("ja-JP")}
          </time>
        </span>
        {!editing && (
          <div className="flex gap-1">
            {memo.can_edit && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={pending}
                onClick={() => {
                  setBody(memo.body);
                  update.reset();
                  remove.reset();
                  setEditing(true);
                }}
              >
                編集
              </Button>
            )}
            {memo.can_delete && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={pending}
                onClick={() => {
                  if (confirm("このメモを削除します。よろしいですか？")) remove.mutate();
                }}
              >
                {remove.isPending ? "削除中..." : "削除"}
              </Button>
            )}
          </div>
        )}
      </div>
      {editing ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (body.trim() && !pending) update.mutate();
          }}
        >
          <Label htmlFor={`memo-${memo.id}`}>メモを編集</Label>
          <Textarea
            id={`memo-${memo.id}`}
            value={body}
            rows={4}
            autoFocus
            required
            maxLength={MAX_MEMO_LENGTH}
            disabled={pending}
            onChange={(event) => {
              setBody(event.target.value);
              update.reset();
            }}
          />
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={pending}
              onClick={() => {
                setEditing(false);
                update.reset();
              }}
            >
              キャンセル
            </Button>
            <Button type="submit" size="sm" disabled={!body.trim() || pending}>
              {update.isPending ? "保存中..." : "保存"}
            </Button>
          </div>
        </form>
      ) : (
        <p className="whitespace-pre-wrap break-words text-sm">{memo.body}</p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {errorMessage(error)}
        </p>
      )}
    </li>
  );
}
