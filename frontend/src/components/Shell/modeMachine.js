// Durable workspace mode is ordinary state. The only transient React projection
// left here is drag-preview: dragging a Standard tab temporarily reveals Builder
// before a valid drop commits it. Visual Standard ↔ Builder motion belongs to the
// browser's View Transition transaction (useModeViewTransition), not this reducer.

export function initialModeState(committedMode = 'panes') {
  return {
    committedMode: committedMode === 'single' ? 'single' : 'panes',
    transition: null,
    nextId: 1,
  }
}

export function modeReducer(state, event) {
  switch (event.type) {
    case 'toggle': {
      const to = event.to || (state.committedMode === 'single' ? 'panes' : 'single')
      if (to === state.committedMode && !state.transition) return state
      return { ...state, committedMode: to, transition: null }
    }
    case 'undo': {
      const to = event.restoredMode === 'single' ? 'single' : 'panes'
      if (to === state.committedMode && !state.transition) return state
      return { ...state, committedMode: to, transition: null }
    }
    case 'drag-arm': {
      if (state.committedMode !== 'single') {
        return state.transition ? { ...state, transition: null } : state
      }
      const id = state.nextId
      return {
        committedMode: 'single',
        transition: {
          id,
          phase: 'drag-preview',
          from: 'single',
          to: 'single',
          cause: 'drag',
        },
        nextId: id + 1,
      }
    }
    case 'drag-cancel': {
      const live = state.transition
      if (!live || live.phase !== 'drag-preview' || live.id !== event.id) return state
      return { ...state, transition: null }
    }
    case 'drag-commit': {
      const live = state.transition
      if (!live || live.phase !== 'drag-preview' || live.id !== event.id) return state
      return { ...state, committedMode: 'panes', transition: null }
    }
    case 'sync-committed': {
      const to = event.committedMode === 'single' ? 'single' : 'panes'
      if (to === state.committedMode && !state.transition) return state
      return { ...state, committedMode: to, transition: null }
    }
    default:
      return state
  }
}

function clampMode(committedMode, splitsEnabled) {
  if (!splitsEnabled) return 'single'
  return committedMode
}

export function effectiveViewMode(state, { splitsEnabled = true } = {}) {
  if (!splitsEnabled) return 'single'
  if (state.transition?.phase === 'drag-preview') return 'panes'
  return clampMode(state.committedMode, splitsEnabled)
}

export function builderModeActive(state, { splitsEnabled = true } = {}) {
  return clampMode(state.committedMode, splitsEnabled) === 'panes'
}

export function dragPreviewActive(state, { splitsEnabled = true } = {}) {
  return !!splitsEnabled && state.transition?.phase === 'drag-preview'
}
