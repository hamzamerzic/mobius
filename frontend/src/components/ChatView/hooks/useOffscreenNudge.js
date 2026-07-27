/* Tracks whether a footer attention target is outside the chat viewport. */
import {
  useCallback,
  useLayoutEffect,
  useState,
} from 'react'


export function isElementOffscreen(scrollEl, element) {
  if (!scrollEl || !element) return false
  const viewport = scrollEl.getBoundingClientRect()
  const target = element.getBoundingClientRect()
  return target.bottom <= viewport.top || target.top >= viewport.bottom
}


export function isIntersectionOffscreen(entry) {
  if (!entry) return false
  // Edge-adjacent rectangles count as intersecting even when they share zero
  // pixels. Keep observer delivery aligned with the synchronous geometry path.
  return !entry.isIntersecting || entry.intersectionRatio <= 0
}


/**
 * Publishes the DOM node a nudge watches, as a render input.
 *
 * The watched card is NOT one durable node. A pending question is rendered by
 * the live streaming <li> while the turn runs and by the DURABLE message row
 * once the turn parks (streamItemQuestionKeys suppresses whichever copy is not
 * current), so React genuinely mounts a NEW element mid-turn. Node identity is
 * therefore the only honest dependency for the observer below, and it must
 * arrive through STATE: a `useRef` mutation does not re-render, so the effect
 * would never re-run and the observer would stay bound to the detached node.
 * With the turn parked awaiting an answer nothing else re-renders, so that
 * observer is the only signal that could ever clear the cue.
 *
 * Returns `[element, ref]`. Attach `ref` to the element that IS the target,
 * and only while it is the pending one; every render path for that card must
 * publish through this same channel so a surface handoff is just a node swap.
 */
export function useNudgeTargetRef() {
  const [element, setElement] = useState(null)
  // Stable identity: this ref is passed as a prop across memoized component
  // boundaries (MsgContent, ActiveAssistantSurface), which compare by identity.
  const ref = useCallback(node => setElement(node ?? null), [])
  return [element, ref]
}


// `element` is the node to watch — the hook is not given a way to FIND it.
// Handing it the node makes a stale observer unrepresentable: any swap of the
// rendering surface changes this identity, so the effect re-binds by
// construction instead of relying on a caller to enumerate rebind triggers.
export default function useOffscreenNudge(scrollRef, active, element) {
  const [offscreen, setOffscreen] = useState(false)

  useLayoutEffect(() => {
    if (!active) {
      setOffscreen(false)
      return undefined
    }

    const scrollEl = scrollRef.current
    if (!scrollEl || !element) {
      setOffscreen(false)
      return undefined
    }

    // IntersectionObserver reports after paint. Recompute from the committed
    // geometry first so a newly visible card cannot paint beneath a stale
    // "tap to answer" cue while that callback is still queued.
    setOffscreen(isElementOffscreen(scrollEl, element))

    if (typeof IntersectionObserver === 'undefined') return undefined
    const observer = new IntersectionObserver(entries => {
      setOffscreen(isIntersectionOffscreen(entries[0]))
    }, { root: scrollEl, threshold: 0 })
    observer.observe(element)
    return () => observer.disconnect()
  }, [active, scrollRef, element])

  return offscreen
}
