import assert from 'node:assert/strict'
import test from 'node:test'

import useOpenAppCtaAutoDismiss from '../useOpenAppCtaAutoDismiss.js'
import { renderHook } from './react-hook-shim.mjs'

const app = (overrides = {}) => ({
  id: 42,
  name: 'Habits',
  updated_at: 'build-1',
  preview_seen_updated_at: null,
  preview_seen_final: false,
  ...overrides,
})

function fakeTimers() {
  let nextId = 1
  const scheduled = new Map()
  const cleared = []
  return {
    scheduled,
    cleared,
    setTimer(fn, delay) {
      const id = nextId++
      scheduled.set(id, { fn, delay })
      return id
    },
    clearTimer(id) {
      cleared.push(id)
      scheduled.delete(id)
    },
    fire(id) {
      const timer = scheduled.get(id)
      scheduled.delete(id)
      timer?.fn()
    },
  }
}

function args(overrides = {}) {
  return {
    builtApps: [app()],
    turnActive: true,
    hidden: false,
    onDismissApp() {},
    ...overrides,
  }
}

test('the clock starts when a visible chat first presents the shortcut', () => {
  const timers = fakeTimers()
  const dismissed = []
  const hookArgs = args({ onDismissApp: value => dismissed.push(value) })
  const hook = renderHook(useOpenAppCtaAutoDismiss, hookArgs, timers)

  assert.equal(timers.scheduled.size, 1)
  const [timerId, timer] = [...timers.scheduled.entries()][0]
  assert.equal(timer.delay, 5000)

  // Turn completion changes the label, but the continuously visible shortcut
  // keeps the clock that started when the owner first saw it.
  hook.rerender({ ...hookArgs, turnActive: false }, timers)
  assert.equal(timers.scheduled.size, 1)
  assert.deepEqual(timers.cleared, [])

  timers.fire(timerId)
  assert.deepEqual(dismissed, [hookArgs.builtApps[0]])
})

test('a hidden chat starts no clock until the owner enters it', () => {
  const timers = fakeTimers()
  const hookArgs = args({ hidden: true })
  const hook = renderHook(useOpenAppCtaAutoDismiss, hookArgs, timers)

  assert.equal(timers.scheduled.size, 0)
  hook.rerender({ ...hookArgs, hidden: false }, timers)
  assert.equal(timers.scheduled.size, 1)
})

test('new previews do not reset shortcuts that are already counting down', () => {
  const timers = fakeTimers()
  const first = app()
  const hookArgs = args({ builtApps: [first] })
  const hook = renderHook(useOpenAppCtaAutoDismiss, hookArgs, timers)
  const [firstTimerId] = timers.scheduled.keys()

  const second = app({ id: 43, updated_at: 'build-2' })
  hook.rerender({ ...hookArgs, builtApps: [first, second] }, timers)

  assert.equal(timers.scheduled.size, 2)
  assert.equal(timers.scheduled.has(firstTimerId), true)
  assert.deepEqual(timers.cleared, [])
  hook.unmount()
  assert.equal(timers.scheduled.size, 0)
})

test('opening a preview cancels its pending retirement', () => {
  const timers = fakeTimers()
  const hookArgs = args()
  const hook = renderHook(useOpenAppCtaAutoDismiss, hookArgs, timers)
  const [timerId] = timers.scheduled.keys()

  hook.rerender({
    ...hookArgs,
    builtApps: [app({ preview_seen_updated_at: 'build-1' })],
  }, timers)

  assert.equal(timers.scheduled.size, 0)
  assert.deepEqual(timers.cleared, [timerId])
})
