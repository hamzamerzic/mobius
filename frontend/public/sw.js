// Service worker: PWA install + Web Push + runtime asset caching.
//
// Cache strategy by URL:
//   /vendor/*                   cache-first  (immutable bundled libs)
//   /assets/*                   cache-first  (Vite-hashed shell assets)
//   /api/apps/{id}/module       SWR          (recompiled bundles via versioned URL)
//   /api/proxy?url=*.{img/font} SWR          (cacheable static assets only)
//   esm.sh/*                    cache-first  (versioned URLs are immutable)
// Everything else (HTML, /api/*) goes straight to the network.
//
// Bumping VERSION purges old caches on activate.
const VERSION = 'v1'
const CACHES = {
  vendor: `mobius-vendor-${VERSION}`,
  assets: `mobius-assets-${VERSION}`,
  apps: `mobius-apps-${VERSION}`,
  proxy: `mobius-proxy-${VERSION}`,
  esm: `mobius-esm-${VERSION}`,
}
const KNOWN_CACHE_NAMES = new Set(Object.values(CACHES))

// File-extension allowlist for /api/proxy SWR — anything else (JSON
// APIs that change frequently, like ISS positions) bypasses cache so
// the live data isn't frozen.
const CACHEABLE_PROXY_EXT =
  /\.(jpg|jpeg|png|gif|webp|svg|ico|woff2?|ttf|otf|eot|hdr|exr|mp3|mp4|webm|ogg|wav)(\?|$)/i

self.addEventListener('install', () => self.skipWaiting())

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys()
    await Promise.all(
      keys
        .filter(k => k.startsWith('mobius-') && !KNOWN_CACHE_NAMES.has(k))
        .map(k => caches.delete(k))
    )
    await self.clients.claim()
  })())
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  const path = url.pathname

  if (url.origin === self.location.origin) {
    if (path.startsWith('/vendor/')) {
      event.respondWith(cacheFirst(req, CACHES.vendor))
      return
    }
    if (path.startsWith('/assets/')) {
      event.respondWith(cacheFirst(req, CACHES.assets))
      return
    }
    if (/^\/api\/apps\/\d+\/module/.test(path)) {
      event.respondWith(staleWhileRevalidate(req, CACHES.apps))
      return
    }
    if (path === '/api/proxy') {
      const upstream = url.searchParams.get('url') || ''
      if (CACHEABLE_PROXY_EXT.test(upstream)) {
        event.respondWith(staleWhileRevalidate(req, CACHES.proxy))
      }
      return
    }
    return
  }

  if (url.hostname === 'esm.sh') {
    event.respondWith(cacheFirst(req, CACHES.esm))
  }
})

async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName)
  const cached = await cache.match(req)
  if (cached) return cached
  try {
    const res = await fetch(req)
    if (res.ok) cache.put(req, res.clone()).catch(() => {})
    return res
  } catch (err) {
    return cached || Response.error()
  }
}

async function staleWhileRevalidate(req, cacheName) {
  const cache = await caches.open(cacheName)
  const cached = await cache.match(req)
  const network = fetch(req).then(res => {
    if (res.ok) cache.put(req, res.clone()).catch(() => {})
    return res
  }).catch(() => cached)
  return cached || network
}

// Web Push: show notification when a push arrives.
self.addEventListener('push', (e) => {
  if (!e.data) return
  const data = e.data.json()
  const options = {
    body: data.body || '',
    icon: data.icon || '/moebius.png',
    badge: '/moebius.png',
    data: { target: data.target || '/', actions: data.actions },
    actions: (data.actions || []).slice(0, 2).map(a => ({
      action: a.action,
      title: a.title,
    })),
  }
  e.waitUntil(self.registration.showNotification(data.title, options))
})

// Notification tap: deep-link into the PWA.
self.addEventListener('notificationclick', (e) => {
  e.notification.close()
  const data = e.notification.data || {}
  let target = data.target || '/'

  if (e.action && data.actions) {
    const match = data.actions.find(a => a.action === e.action)
    if (match && match.target) target = match.target
  }

  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then(windowClients => {
        for (const clien