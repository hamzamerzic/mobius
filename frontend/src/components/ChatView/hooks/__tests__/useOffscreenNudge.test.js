/**
 * Regression tests for the sticky question / Resume attention cue.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { renderHook } from './react-hook-shim.mjs'
import useOffscreenNudge, {
  isElementOffscreen,
} from '../useOffscreenNudge.js'


function rect(top, bottom) {
  return { top, bottom }
}

function elementAt(top, bottom) {
  return { getBoundingClientRect: () => rect(top, bottom) }
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

test('mount computes committed geometry before observer delivery', () => {
  const originalObserver = globalThis.IntersectionObserver
  class IdleObserver {
    observe() {}
    disconnect() {}
  }
  globalThis.IntersectionObserver = IdleObserver

  try {
    const scrollRef = { current: elementAt(100, 500) }
    const visible = elementAt(200, 400)
    const { result, rerender } = renderHook(
      useOffscreenNudge,
      scrollRef,
      true,
      () => visible,
      ['messages-v1'],
    )
    assert.equal(result.current, false,
      'a visible question must not wait for IntersectionObserver to hide the cue')

    const hiddenBelow = elementAt(600, 800)
    rerender(
      scrollRef,
      true,
      () => hiddenBelow,
      ['messages-v2'],
    )
    assert.equal(result.current, true,
      'a newly rebound offscreen question is exposed in the same layout pass')
  } finally {
    globalThis.IntersectionObserver = originalObserver
  }
})
