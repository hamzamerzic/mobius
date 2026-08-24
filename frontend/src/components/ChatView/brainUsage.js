/** Pure conversions for the composer's two brain gauges. */

function clampPercent(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return Math.min(100, Math.max(0, value))
}

export function contextTokenCounts(snapshot) {
  const input = snapshot?.input_tokens
  const window = snapshot?.context_window
  if (
    typeof input !== 'number'
    || !Number.isFinite(input)
    || typeof window !== 'number'
    || !Number.isFinite(window)
    || window <= 0
  ) {
    return null
  }
  return {
    used: Math.max(0, Math.round(input)),
    maximum: Math.round(window),
  }
}

export function formatTokenCount(value) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value)
}

export function contextUsedPercent(snapshot) {
  const tokens = contextTokenCounts(snapshot)
  return tokens === null ? null : clampPercent((tokens.used / tokens.maximum) * 100)
}
