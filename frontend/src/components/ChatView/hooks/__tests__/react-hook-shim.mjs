// Minimal React hooks shim for unit-testing pure hook logic with
// `node --test`. Re-implements just enough of React's hook contract
// (call-order indexing, stable refs across re-renders, useState
// updater functions) to exercise the hooks in this directory.
//
// This is intentionally NOT a general-purpose React test renderer —
// we don't need rendering, batching, concurrent mode, or effects.
// We just need useState / useRef / useCallback to behave like React
// during synchronous test invocations of a hook function.
//
// Why this instead of @testing-library/react-hooks: zero new
// devDependencies, fits the Möbius preference for keeping the
// frontend toolchain minimal (Vite defaults + Playwright).

let _slots = []
let _slotIndex = 0
let _rerender = () => {}

export function __reset() {
  _slots = []
  _slotIndex = 0
}

export function __setRerender(fn) {
  _rerender = fn
}

export function useState(initial) {
  const i = _slotIndex++
  if (_slots[i] === undefined) {
    _slots[i] = {
      value: typeof initial === 'function' ? initial() : initial,
    }
  }
  const slot = _slots[i]
  const setter = (next) => {
    slot.value = typeof next === 'function' ? next(slot.value) : next
    _rerender()
  }
  return [slot.value, setter]
}

export function useRef(initial) {
  const i = _slotIndex++
  if (_slots[i] === undefined) {
    _slots[i] = { current: initial }
  }
  return _slots[i]
}

export function useCallback(fn /*, deps */) {
  // The hooks under test rely on useCallback for identity stability
  // but our tests don't observe identity across re-renders. Returning
  // the function as-is preserves call semantics.
  const i = _slotIndex++
  if (_slots[i] === undefined) {
    _slots[i] = { fn }
  } else {
    _slots[i].fn = fn
  }
  return _slots[i].fn
}

/**
 * Run a hook function as if React were mounting it. Returns a
 * { result, rerender } pair; `result.current` reflects the latest
 * return value, and `rerender(...args)` re-invokes the hook with
 * fresh arguments while preserving slot state.
 */
export function renderHook(hookFn, ...initialArgs) {
  __reset()
  const result = { current: undefined }
  let currentArgs = initialArgs
  function run() {
    _slotIndex = 0
    result.current = hookFn(...currentArgs)
  }
  __setRerender(run)
  run()
  return {
    result,
    rerender: (...nextArgs) => {
      currentArgs = nextArgs.length > 0 ? nextArgs : currentArgs
      run()
    },
  }
}
