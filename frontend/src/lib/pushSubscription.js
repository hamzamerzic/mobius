import { api } from '../api/client.js'

/**
 * Web Push subscription lifecycle, kept out of React so it can be exercised
 * directly.
 *
 * The subscription lives on a dedicated worker at `/shell/push/` rather than
 * the shell's `/`-scoped caching worker: Android routes a push to an installed
 * app only when the SERVICE WORKER'S SCOPE falls inside that app's manifest
 * scope, and `/` is outside the shell's `/shell/`. `public/sw-push.js` carries
 * the full reasoning, including why the extra path segment matters.
 */
export const PUSH_SW_URL = '/sw-push.js'
export const PUSH_SW_SCOPE = '/shell/push/'

/** Register the push worker and resolve once it has an active worker. */
export async function activatePushWorker(container) {
  const registration = await container.register(
    PUSH_SW_URL, { scope: PUSH_SW_SCOPE },
  )
  if (registration.active) return registration
  const worker = registration.installing || registration.waiting
  if (!worker) return registration
  // pushManager.subscribe() needs an active worker, and a fresh registration
  // is still installing on the first load after this ships.
  await new Promise((resolve) => {
    const onChange = () => {
      if (worker.state === 'activated' || worker.state === 'redundant') {
        worker.removeEventListener('statechange', onChange)
        resolve()
      }
    }
    worker.addEventListener('statechange', onChange)
    onChange()
  })
  return registration
}

/**
 * Retire subscriptions an older release left on the caching worker.
 *
 * That worker no longer has a `push` handler, so a send to its endpoint would
 * trip the browser's userVisibleOnly fallback and show a generic "site updated
 * in the background" notification. Drop it server-side first, then locally, so
 * a failure can't strand an endpoint in the database still receiving sends.
 * The registration itself is left alone — it is the shell's cache.
 */
export async function retireLegacySubscriptions(
  container, currentEndpoint, push = api.push,
) {
  const registrations = await container.getRegistrations()
  for (const registration of registrations) {
    if (registration.scope.endsWith(PUSH_SW_SCOPE)) continue
    try {
      const stale = await registration.pushManager.getSubscription()
      if (!stale || stale.endpoint === currentEndpoint) continue
      await push.unsubscribe({ endpoint: stale.endpoint })
      await stale.unsubscribe()
    } catch {
      // A registration without push, or a revoked permission — nothing to
      // retire. The backend also prunes endpoints that answer 410.
    }
  }
}

/** base64url VAPID key → the Uint8Array `subscribe()` wants. */
function applicationServerKey(publicKey) {
  const padding = '='.repeat((4 - publicKey.length % 4) % 4)
  const raw = atob(publicKey.replace(/-/g, '+').replace(/_/g, '/') + padding)
  const key = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) key[i] = raw.charCodeAt(i)
  return key
}

/**
 * Subscribe this browser to Web Push and hand the subscription to the server.
 * Safe to call on every session — subscriptions rotate, and the browser only
 * prompts for permission once.
 */
export async function subscribeToPush({
  container = globalThis.navigator?.serviceWorker,
  push = api.push,
} = {}) {
  const registration = await activatePushWorker(container)

  const res = await push.vapidKey()
  if (!res.ok) return null
  const { publicKey } = await res.json()

  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: applicationServerKey(publicKey),
  })

  const { endpoint, keys } = subscription.toJSON()
  await push.subscribe({ endpoint, keys })

  // Only once the replacement is registered server-side.
  await retireLegacySubscriptions(container, endpoint, push)
  return subscription
}
