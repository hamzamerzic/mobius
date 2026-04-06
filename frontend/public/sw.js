// Service worker: PWA install support + Web Push notifications.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.map(k => caches.delete(k)))
  ))
})

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

  // If an action button was clicked, use its target.
  if (e.action && data.actions) {
    const match = data.actions.find(a => a.action === e.action)
    if (match && match.target) target = match.target
  }

  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then(windowClients => {
        // Focus existing PWA window and navigate.
        for (const client of windowClients) {
          if (new URL(client.url).origin === self.location.origin) {
            client.focus()
            client.navigate(target)
            return
          }
        }
        // No window open — open a new one.
        return clients.openWindow(target)
      })
  )
})

// Subscription rotation: re-subscribe silently.
self.addEventListener('pushsubscriptionchange', (e) => {
  e.waitUntil(
    self.registration.pushManager.subscribe(e.oldSubscription.options)
      .then(newSub => {
        const subJson = newSub.toJSON()
        return fetch('/api/push/subscribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            endpoint: subJson.endpoint,
            keys: subJson.keys,
          }),
        })
      })
  )
})
