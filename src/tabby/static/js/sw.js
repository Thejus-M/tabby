// Network-first for pages and API, cache-first for static assets, so the app shell opens offline.
const CACHE = "tabby-v2";
const SHELL = ["/", "/static/css/app.css", "/static/js/app.js", "/static/js/alpine.min.js", "/static/icons/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
    return;
  }
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (url.pathname === "/") caches.open(CACHE).then((c) => c.put("/", res.clone()));
        return res;
      })
      .catch(() => caches.match(e.request).then((hit) => hit || caches.match("/"))),
  );
});
