/**
 * Unit tests for useBridgePartial.
 *
 * Run with:
 *   cd frontend && node --loader=./src/components/ChatView/hooks/__tests__/react-loader.mjs \
 *     --test src/components/ChatView/hooks/__tests__/useBridgePartial.test.js
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { renderHook } from './react-hook-shim.mjs'
import useBridgePartial from '../useBridgePartial.js'

test('shouldBridge is true when running at mount and last-message ts matches', () => {
  const { result } = renderHook(useBridgePartial, {
    runningAtMount: true,
    lastMsgAtMount: { ts: 555, role: 'assistant' },
  })
  assert.equal(result.current.shouldBridge({ ts: 555 }), true)
})

test('shouldBridge is false after markBridged (one-shot)', () => {
  const { result } = renderHook(useBridgePartial, {
    runningAtMount: true,
    lastMsgAtMount: { ts: 555, role: 'assistant' },
  })
  assert.equal(result.current.shouldBridge({ ts: 555 }), true)
  result.current.markBridged()
  assert.equal(result.current.shouldBridge({ ts: 555 }), false)
})

test('shouldBridge is false when runningAtMount is false', () => {
  const { result } = renderHook(useBridgePartial, {
    runningAtMount: false,
    lastMsgAtMount: { ts: 555, role: 'assistant' },
  })
  assert.equal(result.current.shouldBridge({ ts: 555 }), false)
})

test('shouldBridge is false when lastMsgAtMount is null', () => {
  const { result } = renderHook(useBridgePartial, {
    runningAtMount: true,
    lastMsgAtMount: null,
  })
  assert.equal(result.current.shouldBridge({ ts: 1 }), false)
})

test('shouldBridge is false when the current last-ts differs from the captured ts', () => {
  // A new turn since mount has appended a fresh assistant message
  // with its own ts — the kept partial is no longer "last."
  const { result } = renderHook(useBridgePartial, {
    runningAtMount: true,
    lastMsgAtMount: { ts: 555, role: 'assistant' },
  })
  assert.equal(result.current.shouldBridge({ ts: 9999 }), false)
})

test('shouldBridge is FALSE when last message at mount was an error (parallel-agent be32e58)', () => {
  // be32e58 made errors persist as the LAST message in the chat.
  // The earlier role-based check ("last message is assistant")
  // would have bridged an error message into the next turn's
  // promote — corrupting both the error display and the partial.
  // ts-based gating must reject this: error role at mount means
  // no kept-partial-ts is captured, shouldBridge returns false
  // regardless of any subsequent currentLastMsg.ts.
  const { result } = renderHook(useBridgePartial, {
    runningAtMount: true,
    lastMsgAtMount: { ts: 555, role: 'error' },
  })
  assert.equal(result.current.shouldBridge({ ts: 555 }), false)
})

test('shouldBridge is FALSE when last message at mount was a system role', () => {
  const { result } = renderHook(useBridgePartial, {
    runningAtMount: true,
    lastMsgAtMount: { ts: 555, role: 'system' },
  })
  assert.equal(result.current.shouldBridge({ ts: 555 }), false)
})

test('shouldBridge is false when currentLastMsg is null/undefined', () => {
  const { result } = renderHook(useBridgePartial, {
    runningAtMount: true,
    lastMsgAtMount: { ts: 555, role: 'assistant' },
  })
  assert.equal(result.current.shouldBridge(null), false)
  assert.equal(result.current.shouldBridge(undefined), false)
})

test('the captured ts is sticky across re-renders with different args', () => {
  // The mount-time decision is the load-bearing one. A re-render
  // with new args (e.g. parent re-rendered with running=false
  // because state updated elsewhere) MUST NOT clear the captured
  // partial-ts mid-bridge.
  const { result, rerender } = renderHook(useBridgePartial, {
    runningAtMount: true,
    lastMsgAtMount: { ts: 555, role: 'assistant' },
  })
  assert.equal(result.current.shouldBridge({ ts: 555 }), true)
  rerender({ runningAtMount: false, lastMsgAtMount: null })
  assert.equal(result.current.shouldBridge({ ts: 555 }), true)
})
