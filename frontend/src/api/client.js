/**
 * Fetch wrapper that attaches the JWT token and handles 401 responses.
 */

export function getToken() {
  return localStorage.getItem('token')
}

export function setToken(token) {
  localStorage.setItem('token', token)
}

export function clearToken() {
  localStorage.removeItem('token')
}

// Set during the setup wizard so background 401s (from service workers
// or stale tabs) don't nuke the freshly-issued token and reload the page
// before provider auth completes.
let _setupInProgress = false
export function setSetupInProgress(v) { _setupInProgress = v }

export async function apiFetch(path, options = {}) {
  const token = getToken()
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  }

  const res = await fetch(`/api${path}`, { ...options, headers })

  if (res.status === 401 && !_setupInProgress) {
    clearToken()
    try { sessionStorage.setItem('auth_expired', '1') } catch {}
    window.location.reload()
    return new Promise(() => {})  // never resolves — page is reloading
  }

  return res
}
