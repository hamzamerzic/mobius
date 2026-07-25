// Pure presentation helpers for the notifications page, split out of the JSX
// so `node --test` covers them without a DOM (the settingsTab.test.js posture).

// Compact relative timestamp for a notification row. Coarse on purpose — the
// page is a history list, not a clock. Falls back to a local date for
// anything older than a week or unparseable.
export function formatRelativeTime(isoString, now = Date.now()) {
  const t = Date.parse(isoString)
  if (!Number.isFinite(t)) return ''
  const diff = now - t
  if (diff < 60_000) return 'now'
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  try {
    return new Date(t).toLocaleDateString()
  } catch {
    return ''
  }
}

// Row icon selection is keyed by source_type — a SERVER-controlled field —
// never by the row's `icon` URL, which an app-scoped sender writes free-form
// and therefore is untrusted (trust pre-flight §1). Unknown slugs get the
// default so a new producer degrades gracefully.
export const SOURCE_TYPE_ICONS = Object.freeze({
  system: 'system',
  agent: 'agent',
  chat: 'chat',
  app: 'app',
  platform_conflict: 'system',
})

export function iconKindForSource(sourceType) {
  return SOURCE_TYPE_ICONS[sourceType] ?? 'default'
}
