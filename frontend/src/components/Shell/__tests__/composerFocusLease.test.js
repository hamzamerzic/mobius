import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  beginTouchComposerFocusLease,
  releaseComposerFocusLease,
} from '../composerFocusLease.js'

test('touch focus lease starts synchronously with a clean buffer', () => {
  const calls = []
  const el = {
    value: 'stale',
    focus: (...args) => calls.push(args),
  }
  const touchMedia = query => ({
    matches: query === '(hover: none) and (pointer: coarse)',
  })

  assert.equal(beginTouchComposerFocusLease(el, {
    matchMediaImpl: touchMedia,
    activeElement: null,
  }), true)
  assert.equal(el.value, '')
  assert.deepEqual(calls, [[{ preventScroll: true }]])
})

test('touch focus lease resumes a durable draft with the caret at its end', () => {
  const selections = []
  const el = {
    value: '',
    focus() {},
    setSelectionRange: (...args) => selections.push(args),
  }

  assert.equal(beginTouchComposerFocusLease(el, {
    matchMediaImpl: () => ({ matches: true }),
    activeElement: null,
    initialValue: 'draft survives',
  }), true)
  assert.equal(el.value, 'draft survives')
  assert.deepEqual(selections, [[14, 14]])
})

test('touch focus lease stays inert on desktop and releases failed handoffs', () => {
  let blurred = 0
  const el = {
    value: 'draft',
    focus() {},
    blur() { blurred += 1 },
  }
  assert.equal(beginTouchComposerFocusLease(el, {
    matchMediaImpl: () => ({ matches: false }),
    activeElement: null,
  }), false)
  assert.equal(el.value, 'draft')

  releaseComposerFocusLease(el, { activeElement: el })
  assert.equal(blurred, 1)
  assert.equal(el.value, '')
})

test('a stale New chat cannot release the focus lease owned by a newer one', () => {
  let blurred = 0
  const el = {
    value: '',
    focus() {},
    blur() { blurred += 1 },
  }
  const touchMedia = () => ({ matches: true })
  const older = {}
  const newer = {}

  assert.equal(beginTouchComposerFocusLease(el, {
    matchMediaImpl: touchMedia,
    activeElement: null,
    owner: older,
  }), true)
  assert.equal(releaseComposerFocusLease(el, { activeElement: el }), true)
  assert.equal(beginTouchComposerFocusLease(el, {
    matchMediaImpl: touchMedia,
    activeElement: null,
    owner: newer,
  }), true)
  el.value = 'newer draft'

  assert.equal(releaseComposerFocusLease(el, {
    activeElement: el,
    owner: older,
  }), false)
  assert.equal(el.value, 'newer draft')
  assert.equal(blurred, 1)

  assert.equal(releaseComposerFocusLease(el, {
    activeElement: el,
    owner: newer,
  }), true)
  assert.equal(el.value, '')
  assert.equal(blurred, 2)
})
