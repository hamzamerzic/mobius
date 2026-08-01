// The Home Screen icon keeps its original start_url forever. Treat the pass
// as one-launch input: read it only for a standalone app and always normalize
// the visible URL to the pass-free app identity.
export function readInstallPass(search, standaloneApp) {
  if (!standaloneApp) return ''
  try {
    return new URLSearchParams(search).get('pass') || ''
  } catch {
    return ''
  }
}

export function withoutInstallPass(href) {
  try {
    const current = new URL(href)
    current.searchParams.delete('pass')
    return current.pathname + current.search + current.hash
  } catch {
    return null
  }
}
