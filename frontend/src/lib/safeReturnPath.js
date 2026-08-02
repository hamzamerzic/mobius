// Validate a post-authentication destination at one boundary. The returned
// value is always a same-origin absolute path with its query/hash preserved.
export function safeReturnPath(raw, origin) {
  if (typeof raw !== 'string' || !raw || typeof origin !== 'string' || !origin) {
    return null
  }
  if (!raw.startsWith('/')) return null
  if (raw.includes('\\') || /%5c/i.test(raw)) return null

  try {
    const url = new URL(raw, origin)
    if (url.origin !== origin) return null
    if (!url.pathname.startsWith('/') || url.pathname.startsWith('//')) return null
    if (decodeURIComponent(url.pathname).includes('\\')) return null
    return url.pathname + url.search + url.hash
  } catch {
    return null
  }
}

// Send a browser context that may not share the owner's session through the
// authentication boundary, then return it to the exact same-origin app path.
// Encoding the complete target as one query value preserves its own query and
// hash without letting either become part of the outer login URL.
export function loginBoundaryPath(returnPath) {
  return `/?return=${encodeURIComponent(returnPath)}`
}
