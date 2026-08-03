/* Layout-space tests pin the shell's one client-to-layout boundary under author zoom. */

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  captureLayoutSpace,
  clientDeltaToLayout,
  clientPointToLayout,
} from '../layoutSpace.js'

function box({
  left = 0,
  top = 0,
  clientWidth = 900,
  clientHeight = 720,
  layoutWidth = 1000,
  layoutHeight = 800,
  currentCSSZoom = 0.9,
} = {}) {
  return {
    currentCSSZoom,
    clientWidth: layoutWidth,
    clientHeight: layoutHeight,
    offsetWidth: layoutWidth,
    offsetHeight: layoutHeight,
    getBoundingClientRect: () => ({
      left,
      top,
      width: clientWidth,
      height: clientHeight,
    }),
  }
}

test('captureLayoutSpace records the effective 90% client-to-layout scale', () => {
  assert.deepEqual(captureLayoutSpace(box({ left: 288 })), {
    clientLeft: 288,
    clientTop: 0,
    width: 1000,
    height: 800,
    zoom: 0.9,
  })
})

test('the zoomed document root keeps its expanded offset dimensions as layout space', () => {
  const root = box({
    clientWidth: 1080,
    clientHeight: 720,
    layoutWidth: 1200,
    layoutHeight: 800,
  })
  root.clientWidth = 1080
  root.clientHeight = 720
  root.ownerDocument = { documentElement: root }

  const space = captureLayoutSpace(root)

  assert.equal(space.width, 1200)
  assert.equal(space.height, 800)
  assert.deepEqual(clientPointToLayout({ x: 1080, y: 720 }, space), {
    x: 1200,
    y: 800,
  })
})

test('client points and deltas cross the zoom boundary once', () => {
  const space = captureLayoutSpace(box({ left: 288, top: 18 }))

  assert.deepEqual(
    clientPointToLayout({ x: 738, y: 288 }, space),
    { x: 500, y: 300 },
  )
  assert.deepEqual(
    clientDeltaToLayout({ x: 90, y: -45 }, space),
    { x: 100, y: -50 },
  )
})

test('native scale remains an ordinary identity boundary', () => {
  const space = captureLayoutSpace(box({
    left: 20,
    top: 30,
    clientWidth: 500,
    clientHeight: 300,
    layoutWidth: 500,
    layoutHeight: 300,
    currentCSSZoom: 1,
  }))

  assert.deepEqual(clientPointToLayout({ x: 55, y: 70 }, space), { x: 35, y: 40 })
  assert.deepEqual(clientDeltaToLayout({ x: 48, y: 24 }, space), { x: 48, y: 24 })
})

test('the document root computed zoom is the legacy fallback', () => {
  const originalGetComputedStyle = globalThis.getComputedStyle
  const root = { authoredZoom: 0.9 }
  const legacy = box({ currentCSSZoom: undefined })
  legacy.ownerDocument = { documentElement: root }
  globalThis.getComputedStyle = node => ({ zoom: String(node.authoredZoom) })
  let space
  try {
    space = captureLayoutSpace(legacy)
  } finally {
    globalThis.getComputedStyle = originalGetComputedStyle
  }
  assert.equal(space.zoom, 0.9)
})

test('currentCSSZoom does not mistake transform scaling for CSS zoom', () => {
  const transformed = box({
    currentCSSZoom: 0.9,
    clientWidth: 720,
    clientHeight: 576,
  })
  const space = captureLayoutSpace(transformed)
  assert.equal(space.zoom, 0.9)
})

test('currentCSSZoom keeps zero-sized measurement fallbacks finite', () => {
  const zero = {
    currentCSSZoom: 0.9,
    offsetWidth: 0,
    offsetHeight: 0,
    clientWidth: 0,
    clientHeight: 0,
    getBoundingClientRect: () => ({ left: 4, top: 6, width: 0, height: 0 }),
  }
  const space = captureLayoutSpace(zero)

  assert.equal(space.zoom, 0.9)
  assert.deepEqual(clientPointToLayout({ x: 13, y: 15 }, space), { x: 10, y: 10 })
})
