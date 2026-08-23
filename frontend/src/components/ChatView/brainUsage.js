/** Pure conversions for the composer's two brain gauges. */

function clampPercent(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return Math.min(100, Math.max(0, value))
}

export function usedPercentFromRemaining(remainingPercent) {
  const remaining = clampPercent(remainingPercent)
  return remaining === null ? null : 100 - remaining
}

export function contextUsedPercent(snapshot) {
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
  return clampPercent((input / window) * 100)
}
