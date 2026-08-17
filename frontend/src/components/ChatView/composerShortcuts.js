export function resolveComposerEnterAction(event, {
  hasInput = false,
  canSteer = false,
  canRequestSteer = canSteer,
  canSubmitSteer = canRequestSteer,
  isTouchPrimary = false,
} = {}) {
  if (!event || event.key !== 'Enter' || event.shiftKey) return null

  const modifiedEnter = !!(event.metaKey || event.ctrlKey)
  if (!modifiedEnter && isTouchPrimary) return null

  if (hasInput) {
    if (modifiedEnter && canSubmitSteer) return 'submit-steer'
    return 'submit'
  }
  if (canRequestSteer) return 'steer'
  return 'noop'
}

/** Paste-without-formatting chord. ClipboardEvent does not reliably retain
 * keyboard modifiers, so the composer snapshots this during keydown and lets
 * the subsequent paste event consume it. */
export function isPlainTextPasteShortcut(event) {
  return !!(
    String(event?.key || '').toLowerCase() === 'v'
    && event?.shiftKey
    && (event?.metaKey || event?.ctrlKey)
  )
}
