import {
  focusComposerElement,
  placeCaretAtTextEnd,
} from '../ChatView/composerFocusPolicy.js'

const TOUCH_PRIMARY_QUERY = '(hover: none) and (pointer: coarse)'
const leaseOwners = new WeakMap()

/**
 * Keep the software keyboard open across an async New-chat allocation. The
 * lease is focused synchronously inside the owner's tap; the real composer
 * takes that focus once its chat-bound surface mounts.
 */
export function beginTouchComposerFocusLease(el, {
  matchMediaImpl = globalThis.matchMedia,
  activeElement = globalThis.document?.activeElement,
  owner = null,
  initialValue = '',
} = {}) {
  if (!el || activeElement === el || typeof matchMediaImpl !== 'function') return false
  if (matchMediaImpl(TOUCH_PRIMARY_QUERY)?.matches !== true) return false
  el.value = typeof initialValue === 'string' ? initialValue : ''
  const focused = focusComposerElement(el)
  if (focused) {
    leaseOwners.set(el, owner)
    placeCaretAtTextEnd(el)
  }
  return focused
}

export function releaseComposerFocusLease(el, {
  activeElement = globalThis.document?.activeElement,
  owner,
} = {}) {
  if (!el) return false
  if (owner !== undefined && leaseOwners.get(el) !== owner) return false
  leaseOwners.delete(el)
  if (activeElement === el && typeof el.blur === 'function') el.blur()
  el.value = ''
  return true
}
