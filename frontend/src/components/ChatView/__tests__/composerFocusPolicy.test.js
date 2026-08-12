import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  focusComposerElement,
  placeCaretAtTextEnd,
  shouldApplyComposerFocusRequest,
} from '../composerFocusPolicy.js'

test('explicit focus request applies to the matching shell chat', () => {
  assert.equal(shouldApplyComposerFocusRequest({
    focusRequest: { chatId: '42', token: 1, focus: true },
    chatId: 42,
    embedded: false,
  }), true)
})

test('focus request ignores unrelated chats and missing requests', () => {
  assert.equal(shouldApplyComposerFocusRequest({
    focusRequest: null,
    chatId: 42,
  }), false)
  assert.equal(shouldApplyComposerFocusRequest({
    focusRequest: { chatId: '41', token: 1, focus: true },
    chatId: 42,
  }), false)
})

test('draft-only and embedded requests do not focus the composer', () => {
  assert.equal(shouldApplyComposerFocusRequest({
    focusRequest: { chatId: 42, token: 1 },
    chatId: 42,
  }), false)
  assert.equal(shouldApplyComposerFocusRequest({
    focusRequest: { chatId: 42, token: 1, focus: true },
    chatId: 42,
    embedded: true,
  }), false)
})

test('focusComposerElement preserves scroll and the current selection', () => {
  const calls = []
  const selections = []
  const el = {
    value: 'saved draft',
    focus: (...args) => calls.push(args),
    setSelectionRange: (...args) => selections.push(args),
  }
  assert.equal(focusComposerElement(el), true)
  assert.deepEqual(calls, [[{ preventScroll: true }]])
  assert.deepEqual(selections, [[11, 11]])
})

test('focusComposerElement falls back for older focus implementations', () => {
  const calls = []
  const el = {
    focus: (...args) => {
      calls.push(args)
      if (args.length) throw new Error('no options')
    },
  }
  assert.equal(focusComposerElement(el), true)
  assert.deepEqual(calls, [[{ preventScroll: true }], []])
})

test('text controls land at the end whenever their focus surface activates', () => {
  const selections = []
  const el = {
    value: 'custom answer',
    setSelectionRange: (...args) => selections.push(args),
  }

  assert.equal(placeCaretAtTextEnd(el), true)
  assert.deepEqual(selections, [[13, 13]])
  assert.equal(placeCaretAtTextEnd({ value: 'unsupported' }), false)
})
