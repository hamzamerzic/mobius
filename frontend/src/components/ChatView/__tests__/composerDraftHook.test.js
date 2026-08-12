import { test } from 'node:test'
import assert from 'node:assert/strict'
import { renderHook } from '../hooks/__tests__/react-hook-shim.mjs'
import {
  readComposerHandoff,
  stageComposerHandoff,
} from '../composerDraft.js'
import useComposerDraftState from '../hooks/useComposerDraftState.js'

function storageStub() {
  const values = new Map()
  return {
    get length() { return values.size },
    key(index) { return [...values.keys()][index] ?? null },
    getItem(key) { return values.has(key) ? values.get(key) : null },
    setItem(key, value) { values.set(key, String(value)) },
    removeItem(key) { values.delete(key) },
  }
}

test('restoration consumes ordinary handoffs but keeps autosend intent', () => {
  const previousStorage = globalThis.sessionStorage
  const storage = storageStub()
  globalThis.sessionStorage = storage
  try {
    stageComposerHandoff('ordinary-hook', 'Restore this', { autoSend: false })
    const ordinary = renderHook(() => useComposerDraftState({
      chatId: 'ordinary-hook',
      hidden: false,
      inputRef: { current: null },
    }))
    assert.equal(ordinary.result.current.pendingComposerSubmit, null)
    assert.deepEqual(readComposerHandoff('ordinary-hook'), {
      draft: null,
      autoSendDraft: null,
    })
    ordinary.unmount()

    stageComposerHandoff('autosend-hook', 'Send this once', { autoSend: true })
    const hook = renderHook(() => useComposerDraftState({
      chatId: 'autosend-hook',
      hidden: false,
      inputRef: { current: null },
    }))

    assert.deepEqual(hook.result.current.pendingComposerSubmit, {
      token: 'stored-handoff:autosend-hook',
      text: 'Send this once',
      storedHandoff: true,
    })
    assert.deepEqual(readComposerHandoff('autosend-hook'), {
      draft: 'Send this once',
      autoSendDraft: 'Send this once',
    })
    hook.unmount()
  } finally {
    if (previousStorage === undefined) delete globalThis.sessionStorage
    else globalThis.sessionStorage = previousStorage
  }
})
