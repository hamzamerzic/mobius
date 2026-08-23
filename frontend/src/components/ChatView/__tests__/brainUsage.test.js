import test from 'node:test'
import assert from 'node:assert/strict'

import {
  contextUsedPercent,
  usedPercentFromRemaining,
} from '../brainUsage.js'

test('provider gauge fills by usage consumed rather than usage remaining', () => {
  assert.equal(usedPercentFromRemaining(73), 27)
  assert.equal(usedPercentFromRemaining(0), 100)
  assert.equal(usedPercentFromRemaining(100), 0)
  assert.equal(usedPercentFromRemaining(null), null)
})

test('context gauge measures the latest model call against its context window', () => {
  assert.equal(contextUsedPercent({
    input_tokens: 193_800,
    context_window: 258_400,
  }), 75)
  assert.equal(contextUsedPercent({ input_tokens: 300, context_window: 200 }), 100)
  assert.equal(contextUsedPercent({ input_tokens: null, context_window: 200 }), null)
  assert.equal(contextUsedPercent({ input_tokens: 100, context_window: 0 }), null)
})
