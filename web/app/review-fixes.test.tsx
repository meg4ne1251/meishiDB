import { act, createElement, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { authApi, cardsApi, tagsApi } from "@/lib/api";
import type { Card } from "@/lib/types";
import { Providers } from "@/components/providers";
import CardDetailPage from "./cards/[id]/page";
import CardsPage from "./cards/page";
import HomePage from "./page";
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "card-1" }), useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  redirect: (path: string) => { throw new Error(`redirect:${path}`); },
}));
vi.mock("next/headers", () => ({ headers: async () => new Headers({ cookie: "session=token" }) }));
vi.mock("next-themes", () => ({ ThemeProvider: ({ children }: { children: ReactNode }) => children }));
vi.mock("@/components/card-memos", () => ({ CardMemos: () => null }));
vi.mock("@/components/card-image-capture", () => ({
  CardImageCapture: ({ onPicked, label, disabled }: { onPicked: (file: File) => void; label: string; disabled: boolean }) =>
    <button type="button" disabled={disabled} onClick={() => onPicked(new File(["image"], "card.jpg"))}>{label}</button>,
}));
let container: HTMLDivElement, root: Root, client: QueryClient;
const blank: Card = {
  id: "card-1", owner_id: "owner", source: "upload", status: "uploaded", tags: [],
  fields: {
    person_name: "", company: "", person_name_kana: null, department: null, title: null,
    postal_code: null, address: null, phone: null, mobile: null, fax: null, email: null,
    website: null, latitude: null, longitude: null, raw_ocr_text: null, ocr_confidence: null,
  }, shared: false, is_favorite: false,
  image_front_key: null, image_back_key: null,
  created_at: "2026-10-03T00:00:00Z", updated_at: "2026-10-03T00:00:00Z",
};
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.spyOn(cardsApi, "get").mockResolvedValue(blank);
  vi.spyOn(cardsApi, "listShares").mockResolvedValue([]);
  vi.spyOn(tagsApi, "list").mockResolvedValue([]);
});
afterEach(async () => {
  await act(async () => root.unmount()); client.clear(); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});
async function waitFor(check: () => void) {
  await vi.waitFor(async () => {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); }); check();
  });
}
async function render(page: ReactNode) { await act(async () => root.render(createElement(QueryClientProvider, { client }, page))); }
async function click(text: string) {
  const button = Array.from(container.querySelectorAll("button")).find((item) => item.textContent?.trim() === text)!;
  expect(button).toBeDefined(); await act(async () => button.click());
}
async function fill(id: string, value: string) {
  const input = container.querySelector<HTMLInputElement>(`#${id}`)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function submit() {
  await act(async () => container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
}
it("separates account caches and cancels pending queries", async () => {
  const clients: QueryClient[] = []; let finishA: (name: string) => void = () => {};
  function Viewer({ user }: { user: string }) {
    const qc = useQueryClient(); if (!clients.includes(qc)) clients.push(qc);
    const query = useQuery({ queryKey: ["private"], queryFn: () => user === "A" ? new Promise<string>((resolve) => { finishA = resolve; }) : Promise.resolve(user) });
    return <span>{query.data ?? "loading"}</span>;
  }
  await act(async () => root.render(<Providers userId="A"><Viewer user="A" /></Providers>));
  clients[0].setQueryData(["cards"], ["A's card"]);
  await act(async () => root.render(<Providers userId="B"><Viewer user="B" /></Providers>));
  await waitFor(() => expect(container.textContent).toBe("B"));
  await act(async () => finishA("A"));
  expect(container.textContent).toBe("B");
  expect(clients[0].getQueryCache().getAll()).toHaveLength(0);
  expect(clients[1].getQueryData(["cards"])).toBeUndefined();
});
it("shows OCR results and saves only edited fields", async () => {
  const ocr: Card = { ...blank, fields: { ...blank.fields!, person_name: "OCR Person", company: "OCR Company" }, status: "ocr_done" };
  vi.spyOn(cardsApi, "uploadImage").mockResolvedValue(ocr);
  vi.spyOn(cardsApi, "update").mockResolvedValue({ ...ocr, fields: { ...ocr.fields!, person_name: "Edited" } });
  await render(<CardDetailPage />);
  await waitFor(() => expect(container.querySelector("#person_name")).not.toBeNull());
  await click("表面を撮影");
  await waitFor(() => expect(container.querySelector<HTMLInputElement>("#person_name")!.value).toBe("OCR Person"));
  expect(container.querySelector<HTMLInputElement>("#company")!.value).toBe("OCR Company");
  await fill("person_name", "Edited"); await submit();
  await waitFor(() => expect(cardsApi.update).toHaveBeenCalled());
  expect(cardsApi.update).toHaveBeenCalledWith("card-1", { fields: { person_name: "Edited" }, tag_ids: undefined });
});
it("preserves draft fields and tags while applying a refetch", async () => {
  vi.mocked(tagsApi.list).mockResolvedValue([{ id: "tag", name: "Tag", color: null }]);
  await render(<CardDetailPage />);
  await waitFor(() => expect(container.querySelector("#person_name")).not.toBeNull());
  await fill("person_name", "Draft"); await click("Tag");
  await act(async () => client.setQueryData(["card", "card-1"], { ...blank, fields: { person_name: "Remote", company: "Remote company" } }));
  await waitFor(() => expect(container.querySelector<HTMLInputElement>("#company")!.value).toBe("Remote company"));
  expect(container.querySelector<HTMLInputElement>("#person_name")!.value).toBe("Draft");
  vi.spyOn(cardsApi, "update").mockResolvedValue(blank); await submit();
  await waitFor(() => expect(cardsApi.update).toHaveBeenCalledWith("card-1", { fields: { person_name: "Draft" }, tag_ids: ["tag"] }));
});
it("opens page two and resets pagination when filters change", async () => {
  vi.spyOn(cardsApi, "list").mockImplementation(async (params) => ({ total: 51, items: [{ ...blank, id: params?.offset === 50 ? "card-51" : "card-1" }] }));
  await render(<CardsPage />);
  await waitFor(() => expect(container.textContent).toContain("1 / 2")); await click("次へ");
  await waitFor(() => expect(container.querySelector('a[href="/cards/card-51"]')).not.toBeNull());
  expect(cardsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 50, limit: 50 }));
  await click("お気に入り");
  await waitFor(() => expect(cardsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0, favorite: true })));
});
it("redirects authenticated users to cards", async () => {
  vi.spyOn(authApi, "me").mockResolvedValue({ id: "owner", email: "owner@example.com", display_name: "Owner", role: "admin" });
  await expect(HomePage()).rejects.toThrow("redirect:/cards");
});
it("redirects unauthenticated users to login", async () => {
  vi.spyOn(authApi, "me").mockRejectedValue(new Error("unauthenticated"));
  await expect(HomePage()).rejects.toThrow("redirect:/login");
});
