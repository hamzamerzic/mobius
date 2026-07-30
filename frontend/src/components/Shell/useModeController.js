import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef } from 'react'
import { initialModeState, modeReducer } from './modeMachine.js'

// Synchronizes the durable workspace mode with the one transient state that still
// belongs in React: drag-preview. Visual mode motion is a separate browser scene
// transaction; this controller never watches CSS animations or schedules recovery.
export default function useModeController({ committedMode, splitsEnabled = true }) {
  const [state, dispatch] = useReducer(
    modeReducer,
    undefined,
    () => initialModeState(committedMode),
  )
  const stateRef = useRef(state)
  useLayoutEffect(() => { stateRef.current = state }, [state])

  useEffect(() => {
    if (committedMode !== stateRef.current.committedMode) {
      dispatch({ type: 'sync-committed', committedMode })
    }
  }, [committedMode])

  useEffect(() => {
    if (splitsEnabled) return
    dispatch({ type: 'sync-committed', committedMode: 'single' })
  }, [splitsEnabled])

  const toggle = useCallback(({ cause, to } = {}) => {
    const current = stateRef.current.committedMode
    const dest = to || (current === 'single' ? 'panes' : 'single')
    dispatch({ type: 'toggle', cause, to: dest })
    return { to: dest, transitionId: null, animated: false, totalMs: 0 }
  }, [])

  const undo = useCallback(({ restoredMode } = {}) => {
    dispatch({ type: 'undo', restoredMode })
  }, [])

  const dragArm = useCallback(() => {
    const current = stateRef.current
    const id = current.committedMode === 'single' ? current.nextId : null
    dispatch({ type: 'drag-arm' })
    return id
  }, [])
  const dragCancel = useCallback((id) => { dispatch({ type: 'drag-cancel', id }) }, [])
  const dragCommit = useCallback((id) => { dispatch({ type: 'drag-commit', id }) }, [])

  return useMemo(() => ({
    state,
    toggle,
    undo,
    dragArm,
    dragCancel,
    dragCommit,
  }), [state, toggle, undo, dragArm, dragCancel, dragCommit])
}
