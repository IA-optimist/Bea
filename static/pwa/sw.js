// Service worker minimal — cache du shell pour usage hors-ligne du squelette UI.
// Les appels API ne sont jamais mis en cache (toujours réseau).
"use strict";

const CACHE = "bea-pwa-v1";
const SHELL = ["./index.html", "./app.js", "./manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Ne jamais cacher les appels API (santé/missions/etc.)
  if (url.pathname.startsWith("/api") || url.pathname === "/health") return;
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
