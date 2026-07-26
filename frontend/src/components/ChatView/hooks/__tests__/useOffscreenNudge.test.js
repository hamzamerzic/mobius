/**
 * Regression tests for the sticky question / Resume attention cue.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { renderHook } from './react-hook-shim.mjs'
import useOffscreenNudge, {
  isElementOffscreen,
  isIntersectionOffscreen,
  useNudgeTargetRef,
} from '../useOffscreenNudge.js'


function rect(top, bottom) {
  return { top, bottom }
}

function elementAt(top, bottom) {
  return { getBoundingClientRect: () => rect(top, bottom) }
}


// Records every observer the hook creates so a test can prove WHICH node is
// actually being watched. The defect class here is an observer left on a node
// React has detached — invisible if you only read the returned boolean.
function withObserverSpy(run) {
  const original = globalThis.IntersectionObserver
  const created = []
  class SpyObserver {
    constructor(callback) {
      this.callback = callback
      this.observed = []
      this.disconnected = false
      created.push(this)
    }

    observe(element) { this.observed.push(element) }

    disconnect() { this.disconnected = true }

    // Drive the async half of the contract: the browser invokes this after
    // paint whenever the observed node crosses the root's bounds.
    report(isIntersecting) { this.callback([{ isIntersecting }]) }
  }
  globalThis.IntersectionObserver = SpyObserver
  try {
    return run(created)
  } finally {
    globalThis.IntersectionObserver = original
  }
}


// The real wiring: the card publishes its own node through a callback ref and
// the hook watches whatever is currently published. Mirrors ChatView, which
// hands the SAME ref to the live streaming surface and the durable message row.
function useNudgedCard(scrollRef, active) {
  const [element, cardRef] = useNudgeTargetRef()
  const offscreen = useOffscreenNudge(scrollRef, active, element)
  return { offscreen, cardRef }
}


test('visible targets are not offscreen, including partial visibility', () => {
  const viewport = elementAt(100, 500)
  assert.equal(isElementOffscreen(viewport, elementAt(150, 450)), false)
  assert.equal(isElementOffscreen(viewport, elementAt(50, 101)), false)
  assert.equal(isElementOffscreen(viewport, elementAt(499, 600)), false)
})

test('targets entirely above or below the chat viewport are offscreen', () => {
  const viewport = elementAt(100, 500)
  assert.equal(isElementOffscreen(viewport, elementAt(20, 100)), true)
  assert.equal(isElementOffscreen(viewport, elementAt(500, 700)), true)
})

test('observer delivery requires positive visible area', () => {
  assert.equal(isIntersectionOffscreen({
    isIntersecting: true,
    intersectionRatio: 0,
  }), true, 'edge adjacency has no visible pixels')
  assert.equal(isIntersectionOffscreen({
    isIntersecting: true,
    intersectionRatio: 0.01,
  }), false)
  assert.equal(isIntersectionOffscreen({
    isIntersecting: false,
    intersectionRatio: 0,
  }), true)
})

test('mount computes committed geometry before observer delivery', () => {
  withObserverSpy(() => {
    const scrollRef = { current: elementAt(100, 500) }
    const visible = elementAt(200, 400)
    const { result, rerender } = renderHook(
      useOffscreenNudge, scrollRef, true, visible,
    )
    assert.equal(result.current, false,
      'a visible question must not wait for IntersectionObserver to hide the cue')

    const hiddenBelow = elementAt(600, 800)
    rerender(scrollRef, true, hiddenBelow)
    assert.equal(result.current, true,
      'a newly bound offscreen question is exposed in the same layout pass')
  })
})

test('a card publishing through the target ref is observed once it mounts', () => {
  withObserverSpy(created => {
    const scrollRef = { current: elementAt(100, 500) }
    const { result } = renderHook(useNudgedCard, scrollRef, true)
    assert.equal(result.current.offscreen, false,
      'no card has mounted yet, so there is nowhere to nudge the owner toward')
    assert.equal(created.length, 0)

    const card = elementAt(600, 800)
    result.current.cardRef(card)
    assert.equal(result.current.offscreen, true)
    assert.equal(created.length, 1)
    assert.deepEqual(created[0].observed, [card])
  })
})

test('a question card that re-mounts onto a new DOM node keeps the offscreen cue truthful', () => {
  withObserverSpy(created => {
    // The turn is parked on the question, so nothing but the card's own node
    // changes in this commit — exactly the case the old find-at-bind contract
    // missed. The observer stayed on the detached streaming node, and with no
    // further renders coming the pill could never clear again.
    const scrollRef = { current: elementAt(100, 500) }
    const { result } = renderHook(useNudgedCard, scrollRef, true)

    const liveCard = elementAt(600, 800)
    result.current.cardRef(liveCard)
    assert.equal(created.length, 1)

    // Live streaming surface → durable message row: React detaches the removed
    // node's ref, then attaches the new row's.
    result.current.cardRef(null)
    const durableCard = elementAt(620, 820)
    result.current.cardRef(durableCard)

    assert.equal(created[0].disconnected, true,
      'the observer on the detached streaming node must be torn down')
    const bound = created[created.length - 1]
    assert.deepEqual(bound.observed, [durableCard],
      'the node currently rendering the card is the node being observed')
    assert.equal(bound.disconnected, false)
    assert.equal(result.current.offscreen, true,
      'the card is still out of view, so the cue must still be showing')
  })
})

test('the cue clears when the card scrolls into view after a live-to-durable handoff', () => {
  withObserverSpy(created => {
    const scrollRef = { current: elementAt(100, 500) }
    const { result } = renderHook(useNudgedCard, scrollRef, true)

    result.current.cardRef(elementAt(600, 800))
    result.current.cardRef(null)
    result.current.cardRef(elementAt(620, 820))
    assert.equal(result.current.offscreen, true)

    // Post-handoff scroll. Only an observer bound to the CURRENT node can
    // report this, so a stale binding surfaces here as a stuck cue.
    created[created.length - 1].report(true)
    assert.equal(result.current.offscreen, false)
  })
})

test('a handoff onto an already-visible row clears the cue without waiting for the observer', () => {
  withObserverSpy(() => {
    const scrollRef = { current: elementAt(100, 500) }
    const { result } = renderHook(useNudgedCard, scrollRef, true)

    result.current.cardRef(elementAt(600, 800))
    assert.equal(result.current.offscreen, true)

    // The durable row renders where the owner is already looking. The
    // synchronous pre-paint recompute owns this: IntersectionObserver does not
    // deliver until after the next paint, which would leave a frame of cue
    // pointing at a card that is on screen.
    result.current.cardRef(null)
    result.current.cardRef(elementAt(200, 400))
    assert.equal(result.current.offscreen, false)
  })
})

test('an unmounting card clears the cue and releases its observer', () => {
  withObserverSpy(created => {
    const scrollRef = { current: elementAt(100, 500) }
    const { result } = renderHook(useNudgedCard, scrollRef, true)

    result.current.cardRef(elementAt(600, 800))
    assert.equal(result.current.offscreen, true)

    result.current.cardRef(null)
    assert.equal(result.current.offscreen, false,
      'there is no card left to send the owner back to')
    assert.equal(created[0].disconnected, true)
  })
})

test('the cue retires when the pending state ends even with the card still mounted', () => {
  withObserverSpy(created => {
    const scrollRef = { current: elementAt(100, 500) }
    const offscreenCard = elementAt(600, 800)
    const { result, rerender } = renderHook(
      useOffscreenNudge, scrollRef, true, offscreenCard,
    )
    assert.equal(result.current, true)

    rerender(scrollRef, false, offscreenCard)
    assert.equal(result.current, false,
      'an answered question retires the cue regardless of geometry')
    assert.equal(created[0].disconnected, true)
  })
})

test('the target ref is stable across renders so memoized rows keep publishing', () => {
  const { result } = renderHook(useNudgeTargetRef)
  const [, first] = result.current
  const node = elementAt(0, 10)
  first(node)
  const [element, second] = result.current
  assert.equal(element, node)
  assert.equal(second, first,
    'a fresh ref identity every render would churn every card it is passed to')
})

test('leaving the chat disconnects the observer', () => {
  // The teardown no dep change can reach. Without it a chat switch leaves a
  // live IntersectionObserver rooted at the old scroll container for every
  // parked question the owner ever scrolled away from.
  withObserverSpy(created => {
    const scrollRef = { current: elementAt(100, 500) }
    const { result, unmount } = renderHook(useNudgedCard, scrollRef, true)

    result.current.cardRef(elementAt(600, 800))
    assert.equal(created.length, 1)
    assert.equal(created[0].disconnected, false)

    unmount()
    assert.equal(created[0].disconnected, true,
      'the observer must be released with the component, not leaked')
  })
})

test('a batched live-to-durable handoff never blanks the cue', () => {
  // React commits the retiring surface's `ref(null)` and the arriving
  // surface's `ref(node)` in ONE pass, so the intermediate "no element" state
  // is never rendered. The hook must therefore reach the new node's geometry
  // from a single effect run — a handoff that only works because it was
  // observed as two commits would flicker the cue for a frame in the browser.
  withObserverSpy(created => {
    const scrollRef = { current: elementAt(100, 500) }
    const offscreenLive = elementAt(600, 800)
    const offscreenDurable = elementAt(700, 900)
    const { result, rerender } = renderHook(
      useOffscreenNudge, scrollRef, true, offscreenLive,
    )
    assert.equal(result.current, true)
    assert.deepEqual(created[0].observed, [offscreenLive])

    // One render, one new node: exactly what a batched handoff commits.
    rerender(scrollRef, true, offscreenDurable)
    assert.equal(result.current, true, 'the cue stays up across the handoff')
    assert.equal(created.length, 2, 'the observer re-binds to the new node')
    assert.deepEqual(created[1].observed, [offscreenDurable])
    assert.equal(created[0].disconnected, true, 'the old observer is released')
  })
})
