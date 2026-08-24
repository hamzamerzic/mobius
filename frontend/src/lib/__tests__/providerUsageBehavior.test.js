import test from 'node:test'
import assert from 'node:assert/strict'

import { weeklyUsagePercent } from '../../components/SettingsView/providerUsage.js'


test('weekly usage follows typed window meaning, not display labels or other limits', () => {
  assert.equal(weeklyUsagePercent({
    state: 'ready',
    windows: [
      { kind: 'other', label: 'Weekly', used_percent: 20 },
      { kind: 'weekly', label: 'Renamed allowance', used_percent: 58 },
      { kind: 'other', label: 'Extra usage', used_percent: 75 },
    ],
  }), 58)
  assert.equal(weeklyUsagePercent({ state: 'ready', windows: [] }), null)
  assert.equal(weeklyUsagePercent({ state: 'unavailable' }), null)
})
