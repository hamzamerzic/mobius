import test from 'node:test'
import assert from 'node:assert/strict'

import {
  contextTokenCounts,
  contextUsedPercent,
  formatTokenCount,
} from '../brainUsage.js'

test('context gauge measures the latest model call against its context window', () => {
  assert.equal(contextUsedPercent({
    input_tokens: 193_800,
    context_window: 258_400,
  }), 75)
  assert.equal(contextUsedPercent({ input_tokens: 300, context_window: 200 }), 100)
  assert.equal(contextUsedPercent({ input_tokens: null, context_window: 200 }), null)
  assert.equal(contextUsedPercent({ input_tokens: 100, context_window: 0 }), null)
})

test('context legend preserves exact current and maximum token counts', () => {
  assert.deepEqual(contextTokenCounts({
    input_tokens: 44_063,
    context_window: 258_400,
  }), { used: 44_063, maximum: 258_400 })
  assert.equal(formatTokenCount(258_400), '258,400')
  assert.equal(contextTokenCounts({ input_tokens: null, context_window: 258_400 }), null)
})
