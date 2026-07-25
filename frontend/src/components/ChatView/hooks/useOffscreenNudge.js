/* Tracks whether a footer attention target is outside the chat viewport. */
import {
  useLayoutEffect,
  useRef,
  useState,
} from 'react'


export function isElementOffscreen(scrollEl, element) {
  if (!scrollEl || !element) return false
  const viewport = scrollEl.getBoundingClientRect()
  const target = element.getBoundingClientRect()
  return target.bottom <= viewport.top || target.top >= viewport.bottom
}


// `findElement` is a fresh closure every render (it reads the live scroll
// ref), so keep it out of the dependency list. Rebinding on every streamed
// token would replace the observer continuously; callers instead provide the
// rendering-surface values that can replace the target node.
export default function useOffscreenNudge(
  scrollRef,
  active,
  findElement,
  rebindDeps,
) {
  const [offscreen, setOffscreen] = useState(false)
  const findElementRef = useRef(findElement)
  findElementRef.current = findElement

  useLayoutEffect(() => {
    if (!active) {
      setOffscreen(false)
      return undefined
    }

    const scrollEl = scrollRef.current
    const element = findElementRef.current()
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
      setOffscreen(!entries[0]?.isIntersecting)
    }, { root: scrollEl, threshold: 0 })
    observer.observe(element)
    return () => observer.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, scrollRef, ...rebindDeps])

  return offscreen
}
