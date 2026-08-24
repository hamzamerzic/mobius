import test from 'node:test'
import assert from 'node:assert/strict'

import { providerAllowance } from '../../components/SettingsView/providerUsage.js'


test('plan providers follow typed weekly meaning, not display labels or other limits', () => {
  assert.deepEqual(providerAllowance('codex', {
    state: 'ready',
    windows: [
      { kind: 'other', label: 'Weekly', used_percent: 20 },
      { kind: 'weekly', label: 'Renamed allowance', used_percent: 58 },
      { kind: 'other', label: 'Extra usage', used_percent: 75 },
    ],
  }), { kind: 'weekly', label: 'Weekly usage', usedPercent: 58 })
  assert.deepEqual(providerAllowance('claude', { state: 'ready', windows: [] }), {
    kind: 'weekly', label: 'Weekly usage', usedPercent: null,
  })
})

test('Möbius follows typed API-credit usage instead of weekly windows', () => {
  assert.deepEqual(providerAllowance('mobius', {
    state: 'ready',
    windows: [
      { kind: 'weekly', used_percent: 80 },
      { kind: 'api_credits', used_percent: 37 },
    ],
  }), { kind: 'api_credits', label: 'API credits usage', usedPercent: 37 })
  assert.deepEqual(providerAllowance('mobius', { state: 'unavailable' }), {
    kind: 'api_credits', label: 'API credits usage', usedPercent: null,
  })
})
