import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { needsModelSelection } from '../modelSelectionPolicy.js'


test('interactive chats require a model before sending', () => {
  assert.equal(needsModelSelection({
    showPicker: true,
    chatInfo: { effective: { model: null } },
  }), true)
  assert.equal(needsModelSelection({
    showPicker: true,
    chatInfo: null,
  }), true)
})

test('an explicit effective model lets the composer send', () => {
  assert.equal(needsModelSelection({
    showPicker: true,
    chatInfo: { effective: { model: 'gpt-5.6-sol' } },
  }), false)
})

test('app embeds that intentionally hide the picker retain their configured send path', () => {
  assert.equal(needsModelSelection({
    showPicker: false,
    chatInfo: { effective: { model: null } },
  }), false)
})

test('the missing-model state opens the picker instead of sending', () => {
  const chatView = readFileSync(new URL('../ChatView.jsx', import.meta.url), 'utf8')
  const popover = readFileSync(new URL('../ComposerPopover.jsx', import.meta.url), 'utf8')
  const picker = readFileSync(new URL('../ChatSettingsPanel.jsx', import.meta.url), 'utf8')

  assert.match(
    chatView,
    /if \(needsModelSelection\(\{ showPicker, chatInfo \}\)\) \{\s*setModelSelectionRequest\(request => request \+ 1\)\s*return\s*\}\s*doSend/,
  )
  assert.match(popover, /modelSelectionRequest[\s\S]*setOpen\(true\)/)
  assert.match(picker, /Choose a model before sending your message\./)
  assert.doesNotMatch(picker, /default model/)
})
