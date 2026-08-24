import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const panel = readFileSync(new URL('../ChatSettingsPanel.jsx', import.meta.url), 'utf8')
const panelCss = readFileSync(new URL('../ChatSettingsPanel.css', import.meta.url), 'utf8')
const manageModels = readFileSync(new URL('../ManageModelsModal.jsx', import.meta.url), 'utf8')

test('chat model surfaces list Möbius after Codex and Claude', () => {
  assert.match(
    panel,
    /export const PROVIDER_ORDER = \['codex', 'claude', 'mobius'\]/,
  )
  assert.match(panel, /mobius:\s*\{[\s\S]*label: 'Möbius subscription'/)
  assert.doesNotMatch(panel, /label: 'Möbius trial'/)
})

test('Möbius models reuse the Android notification mark in the shell ink color', () => {
  assert.match(panel, /className="csp__mobius-logo"/)
  assert.doesNotMatch(panel, /M8\.2 7\.2c-2\.9/)
  assert.match(
    panelCss,
    /mask:\s*url\(['"]\/icons\/notification-badge\.svg['"]\)[^;]*;/,
  )
  assert.match(panelCss, /\.csp__mobius-logo\s*{[\s\S]*background:\s*currentColor;/)
})

test('the public Evolve row does not expose its internal wire id', () => {
  assert.match(
    manageModels,
    /pid !== 'mobius' && \([\s\S]*className="mmm-row__sub"/,
  )
})
