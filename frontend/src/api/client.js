/**
 * Fetch wrapper that attaches the JWT token and handles 401 responses.
 * BASE strips the trailing slash from Vite's BASE_URL so paths like
 * /api/chats work regardless of deployment prefix (e.g. /proxy/8001/).
 */
import { del as idbDel } from 'idb-keyval'

export const BASE = (import.meta.env.BASE_URL || '/').replace(/\/$/, '')

// localStorage access can throw in private-browsing modes or when the
// storage quota is hit. App.jsx reads getToken() during initial render
// to decide between Shell / Login / SetupWizard — an uncaught throw
// here would crash the splash. Wrap all three helpers defensively.
export function getToken() {
  try { return localStorage.getItem('token') } catch { return null }
}

export function setToken(token) {
  try { localStorage.setItem('token', token) } catch {}
}

export function clearToken() {
  try { localStorage.removeItem('token') } catch {}
  // Setup-wizard resume state assumes an active token. If the token
  // is gone (logout / expiry), clear the resume key so the user
  // doesn't get bounced back into the wizard after they re-login.
  try { localStorage.removeItem('setup-step') } catch {}
}

// Wipes persisted client state on logout / token expiry: the
// TanStack Query cache (IndexedDB) AND the SW Cache Storage
// entries. The SW caches mini-app module responses under the full
// request URL — and that URL embeds the per-app scoped token as a
// query param — so without this wipe the prior owner's app tokens
// linger in `mobius-apps-*` after their session ends. Returns a
// promise so callers can `await` it before reloading the page
// (otherwise the browser would abort the in-flight delete).
export function clearQueryCache() {
  return Promise.all([
    idbDel('mobius-query-cache').catch(() => {}),
    wipeSwCaches().catch(() => {}),
  ])
}

async function wipeSwCaches() {
  if (typeof caches === 'undefined') return
  const keys = await caches.keys()
  await Promise.all(
    keys.filter(k => k.startsWith('mobius-')).map(k => caches.delete(k))
  )
}

let _setupInProgress = false
export function setSetupInProgress(v) { _setupInProgress = v }

export async function apiFetch(path, options = {}) {
  const token = getToken()
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  }

  const res = await fetch(`${BASE}/api${path}`, { ...options, headers })

  if (res.status === 401 && !_setupInProgress) {
    clearToken()
    try { sessionStorage.setItem('auth_expired', '1') } catch {}
    // Await the cache wipe before reloading. Without this, the page
    // reload aborts the IndexedDB delete and the next owner could see
    // stale chats/messages from the cached query data.
    await clearQueryCache()
    window.location.reload()
    return new Promise(() => {})
  }

  return res
}
