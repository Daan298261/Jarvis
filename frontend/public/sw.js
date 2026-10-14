const CACHE = "jarvis-shell-personas-20261014"

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(["/", "/phone", "/manifest.webmanifest", "/icon.svg"])).then(() => self.skipWaiting()),
  )
})

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))).then(() => self.clients.claim()),
  )
})

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url)
  if (url.pathname.startsWith("/api") || event.request.method !== "GET") {
    return
  }
  event.respondWith(
    fetch(event.request).then((response) => {
      if (response.ok && url.origin === self.location.origin) {
        const copy = response.clone()
        event.waitUntil(caches.open(CACHE).then(cache => cache.put(event.request, copy)))
      }
      return response
    }).catch(() => caches.match(event.request).then((cached) =>
      cached || (event.request.mode === "navigate" ? caches.match("/") : Response.error()))),
  )
})
