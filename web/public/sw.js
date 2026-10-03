/* Cache only public static assets. Authenticated pages and RSC always use the network. */
const CACHE = "meishidb-v2";
const STATIC_ASSETS = ["/manifest.webmanifest", "/icon.svg"];
const OFFLINE_HTML = '<!doctype html><html lang="ja"><meta charset="utf-8"><title>オフライン</title><body><h1>オフラインです</h1><p>接続を確認して再読み込みしてください。</p></body></html>';

function cacheable(response) {
  const control = response.headers.get("Cache-Control") || "";
  return response.ok && !/private|no-store|no-cache/i.test(control) &&
    !response.headers.has("Set-Cookie") &&
    !/text\/x-component/i.test(response.headers.get("Content-Type") || "");
}

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then(async (cache) => {
    await Promise.all(STATIC_ASSETS.map(async (path) => {
      try {
        const response = await fetch(path);
        if (cacheable(response)) await cache.put(path, response);
      } catch { /* Installation can complete offline. */ }
    }));
  }));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then(async (keys) => {
    await Promise.all(keys.filter((key) => key.startsWith("meishidb-") && key !== CACHE)
      .map((key) => caches.delete(key)));
    await self.clients.claim();
  }));
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => new Response(OFFLINE_HTML, {
      headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
    })));
    return;
  }
  if (req.headers.has("RSC") || req.headers.has("Next-Router-Prefetch") ||
      url.searchParams.has("_rsc")) return;
  if (!url.pathname.startsWith("/_next/static/") && !STATIC_ASSETS.includes(url.pathname)) return;
  const network = fetch(req);
  event.waitUntil(network.then(async (response) => {
    if (cacheable(response)) {
      const cache = await caches.open(CACHE);
      await cache.put(req, response.clone());
    }
  }).catch(() => undefined));
  event.respondWith(caches.open(CACHE).then(async (cache) =>
    (await cache.match(req)) || network.catch(() => Response.error()),
  ));
});
