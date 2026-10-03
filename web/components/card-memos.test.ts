import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, cardsApi } from "@/lib/api";
import type { CardMemo } from "@/lib/types";
import { CardMemos } from "./card-memos";

const memo: CardMemo = {
  id: "memo-1", card_id: "card-1", author_id: "user-1", author_name: "山田",
  body: "展示会で名刺交換\n<script>alert(1)</script>", created_at: "2026-10-03T10:00:00Z",
  can_edit: true, can_delete: true,
};

let container: HTMLDivElement;
let root: Root;
let queryClient: QueryClient;

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.spyOn(cardsApi, "listMemos").mockResolvedValue({ items: [memo], can_create: true });
  vi.spyOn(cardsApi, "createMemo").mockResolvedValue(memo);
  vi.spyOn(cardsApi, "updateMemo").mockResolvedValue(memo);
  vi.spyOn(cardsApi, "deleteMemo").mockResolvedValue(undefined);
});

afterEach(async () => {
  await act(async () => root.unmount());
  queryClient.clear();
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function waitFor(check: () => void) {
  await vi.waitFor(async () => {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    check();
  });
}

async function render() {
  await act(async () => root.render(createElement(QueryClientProvider, { client: queryClient },
    createElement(CardMemos, { cardId: "card-1" }))));
  await waitFor(() => expect(container.textContent).not.toContain("読み込み中..."));
}

async function fill(value: string, selector = "textarea") {
  const textarea = container.querySelector<HTMLTextAreaElement>(selector)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, value);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function submit(selector = "form") {
  await act(async () => {
    container.querySelector(selector)!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

async function click(text: string) {
  const button = Array.from(container.querySelectorAll("button")).find((item) => item.textContent === text);
  expect(button).toBeDefined();
  await act(async () => button!.click());
}

describe("名刺メモ", () => {
  it("shows authors and dates, renders memo text safely, and disables blank submission", async () => {
    await render();
    expect(container.textContent).toContain("山田");
    expect(container.querySelector("time")?.dateTime).toBe(memo.created_at);
    expect(container.textContent).toContain(memo.body);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(true);
    await fill(" \n ");
    await submit();
    expect(cardsApi.createMemo).not.toHaveBeenCalled();
  });

  it("keeps a failed draft, retries creation, clears the saved draft and refreshes the list", async () => {
    vi.mocked(cardsApi.createMemo).mockRejectedValueOnce(new Error("network"));
    await render();
    await fill("  次回、資料を送る  ");
    await submit();
    await waitFor(() => expect(container.querySelector('[role="alert"]')).not.toBeNull());
    expect(container.querySelector("textarea")!.value).toBe("  次回、資料を送る  ");
    await submit();
    await waitFor(() => expect(container.querySelector("textarea")!.value).toBe(""));
    expect(cardsApi.createMemo).toHaveBeenLastCalledWith("card-1", "次回、資料を送る");
    expect(cardsApi.listMemos).toHaveBeenCalledTimes(2);
  });

  it("hides write controls for view shares and can still display their memos", async () => {
    vi.mocked(cardsApi.listMemos).mockResolvedValue({
      items: [{ ...memo, can_edit: false, can_delete: false }], can_create: false,
    });
    await render();
    expect(container.textContent).toContain(memo.body);
    expect(container.querySelector("textarea")).toBeNull();
    expect(container.querySelectorAll("button")).toHaveLength(0);
    expect(container.textContent).toContain("閲覧権限");
  });

  it("allows editing and cancellation, and confirms deletion before calling the API", async () => {
    await render();
    await click("編集");
    await fill("未保存の変更", "li textarea");
    await click("キャンセル");
    expect(cardsApi.updateMemo).not.toHaveBeenCalled();
    await click("編集");
    expect(container.querySelector<HTMLTextAreaElement>("li textarea")!.value).toBe(memo.body);
    await fill("  送付済み  ", "li textarea");
    await submit("li form");
    await waitFor(() => expect(container.querySelector("li textarea")).toBeNull());
    expect(cardsApi.updateMemo).toHaveBeenCalledWith("card-1", "memo-1", "送付済み");
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    await click("削除");
    expect(cardsApi.deleteMemo).not.toHaveBeenCalled();
    vi.mocked(cardsApi.listMemos).mockResolvedValue({ items: [], can_create: true });
    await click("削除");
    await waitFor(() => expect(cardsApi.deleteMemo).toHaveBeenCalledWith("card-1", "memo-1"));
    await waitFor(() => expect(container.textContent).toContain("メモはまだありません"));
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it("shows a retry action on load failure without rendering cached memo content", async () => {
    queryClient.setQueryData(["card", "card-1", "memos"], { items: [memo], can_create: true });
    vi.mocked(cardsApi.listMemos).mockRejectedValueOnce(new ApiError(404, "card not found"));
    await render();
    await waitFor(() => expect(container.textContent).toContain("メモを読み込めませんでした"));
    expect(container.textContent).not.toContain(memo.body);
    await click("再試行");
    await waitFor(() => expect(container.textContent).toContain(memo.body));
  });
});
