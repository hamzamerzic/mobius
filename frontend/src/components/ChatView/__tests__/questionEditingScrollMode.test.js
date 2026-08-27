import test from 'node:test'
import assert from 'node:assert/strict'
import {
  modeForQuestionEditingViewportChange,
  modeForSettledInlineEditorGrowth,
} from '../scroll/geometry.js'

test('question editing rebases only an ordinary held viewport to native caret movement', () => {
  const staleHold = { kind: 'ANCHOR_AT', key: 'before-edit', offset: 20 }
  const caretHold = { kind: 'ANCHOR_AT', key: 'question-row', offset: 84 }
  assert.equal(modeForQuestionEditingViewportChange(staleHold, caretHold), caretHold)

  for (const strongerMode of [
    { kind: 'PIN_USER_MSG', cid: 'c-1' },
    { kind: 'FOLLOW_BOTTOM' },
    {
      kind: 'ANCHOR_AT',
      key: 'question-row',
      offset: 84,
      questionSubmitBaseMode: { kind: 'FOLLOW_BOTTOM' },
    },
  ]) {
    assert.equal(modeForQuestionEditingViewportChange(strongerMode, caretHold), strongerMode)
  }
  assert.equal(modeForQuestionEditingViewportChange(staleHold, null), staleHold)
  assert.equal(
    modeForQuestionEditingViewportChange(caretHold, { ...caretHold }),
    caretHold,
    'an unchanged caret hold does not manufacture a mode transition',
  )
})

test('coalesced textarea growth restores its pre-input reading coordinate', () => {
  const capturedMode = { kind: 'ANCHOR_AT', key: 'question-row', offset: 90.5 }
  const stableViewport = {
    capturedMode,
    beforeEditorHeight: 38,
    afterEditorHeight: 76,
    beforeViewportHeight: 510,
    afterViewportHeight: 510,
    beforeViewportWidth: 426,
    afterViewportWidth: 426,
  }
  assert.equal(
    modeForSettledInlineEditorGrowth(stableViewport),
    capturedMode,
    'a missed editor ResizeObserver entry cannot leave native caret scroll behind',
  )
  assert.equal(
    modeForSettledInlineEditorGrowth({
      ...stableViewport,
      afterEditorHeight: stableViewport.beforeEditorHeight,
    }),
    null,
    'ordinary typing does not manufacture a layout write',
  )
  assert.equal(
    modeForSettledInlineEditorGrowth({
      ...stableViewport,
      afterViewportHeight: 472,
    }),
    null,
    'software-keyboard geometry keeps the browser caret-visible coordinate',
  )
})
