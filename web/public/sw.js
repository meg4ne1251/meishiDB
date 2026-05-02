/* meishiDB minimal service worker.
 *
 * - 静的アセットは stale-while-revalidate
 * - /api 配下はキャッシュしない（常にネットワーク）
 * - ナビゲーション失敗時は /offline にフォールバック
 */

const CACHE = "meishidb-v1";
const STATIC_ASSETS = ["/", "/cards", "/offline", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(STATIC_ASSETS).catch(() => undefined)),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  if (req.method !== "GET") return;
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(() => caches.match("/offline").then((r) => r || Response.error())),
    );
    return;
  }

  event.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const cached = await cache.match(req);
      const network = fetch(req)
        .then((res) => {
          if (res.ok) cache.put(req, res.clone()).catch(() => undefined);
          return res;
        })
        .catch(() => cached);
      return cached || network;
    }),
  );
});
