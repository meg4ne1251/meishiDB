import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { expect, it, vi } from "vitest";
function harness(control = "public, max-age=3600", contentType = "text/javascript") {
  const handlers: Record<string, (event: any) => void> = {};
  const put = vi.fn(async () => {}), remove = vi.fn(async () => true);
  const cache = { put, match: vi.fn(async () => undefined) };
  const caches = { open: vi.fn(async () => cache), keys: vi.fn(async () => ["meishidb-v1", "meishidb-v2", "other-app"]), delete: remove };
  const network = vi.fn(async () => new Response("data", { headers: { "Cache-Control": control, "Content-Type": contentType } }));
  runInNewContext(readFileSync("public/sw.js", "utf8"), {
    self: { addEventListener: (name: string, handler: any) => { handlers[name] = handler; }, location: { origin: "https://meishi.test" }, clients: { claim: vi.fn() }, skipWaiting: vi.fn() },
    caches, fetch: network, URL, Response, Promise,
  });
  async function request(path: string, headers = {}) {
    const waits: Promise<unknown>[] = []; let response: Promise<Response> | undefined;
    handlers.fetch({ request: { method: "GET", mode: "cors", url: `https://meishi.test${path}`, headers: new Headers(headers) }, waitUntil: (p: Promise<unknown>) => waits.push(p), respondWith: (p: Promise<Response>) => { response = p; } });
    await response; await Promise.all(waits); return response;
  }
  return { handlers, put, remove, caches, network, request };
}
it("does not intercept pages, APIs or RSC", async () => {
  const h = harness("private, no-store", "text/x-component");
  for (const path of ["/cards", "/api/cards", "/cards?_rsc=123", "/settings/passkeys", "/_next/image?url=private"]) expect(await h.request(path)).toBeUndefined();
  expect(await h.request("/_next/static/chunk.js", { RSC: "1" })).toBeUndefined();
  expect(h.caches.open).not.toHaveBeenCalled();
});
it("caches public static files", async () => {
  const h = harness(); await h.request("/_next/static/chunk.js"); expect(h.put).toHaveBeenCalledOnce();
});
it.each(["private", "no-store", "public, no-cache"])("does not store %s responses", async (control) => {
  const h = harness(control); await h.request("/_next/static/chunk.js"); expect(h.put).not.toHaveBeenCalled();
});
it("does not store component responses for static URLs", async () => {
  const h = harness("public", "text/x-component"); await h.request("/_next/static/chunk.js"); expect(h.put).not.toHaveBeenCalled();
});
it("removes previous meishiDB caches on activation", async () => {
  const h = harness(); let promise: Promise<unknown> = Promise.resolve();
  h.handlers.activate({ waitUntil: (p: Promise<unknown>) => { promise = p; } }); await promise;
  expect(h.remove).toHaveBeenCalledOnce(); expect(h.remove).toHaveBeenCalledWith("meishidb-v1");
});
