import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import StandaloneInstallCard from '../../components/StandaloneApp/StandaloneInstallCard.jsx'
import {
  getInstallPromptSnapshot,
  startInstallPromptCapture,
} from '../installPrompt.js'

function standaloneTarget() {
  const handlers = new Map()
  return {
    navigator: { standalone: false },
    matchMedia: () => ({ matches: true }),
    addEventListener(type, handler) { handlers.set(type, handler) },
    dispatch(type, event = {}) { handlers.get(type)?.(event) },
  }
}

test('a mini-app prompt in a standalone shell reaches the card as Install', () => {
  const target = standaloneTarget()
  startInstallPromptCapture(target)
  assert.equal(getInstallPromptSnapshot(), 'installed')

  target.dispatch('beforeinstallprompt', {
    preventDefault() {},
    async prompt() { return { outcome: 'accepted' } },
  })
  assert.equal(getInstallPromptSnapshot(), 'ready')

  const html = renderToStaticMarkup(createElement(StandaloneInstallCard, {
    app: { slug: 'notes', name: 'Notes', updated_at: '1' },
    forceOpen: true,
  }))
  assert.match(html, />Install<\/button>/)
  assert.doesNotMatch(html, /already on your home screen/i)

  target.dispatch('appinstalled')
  const successHtml = renderToStaticMarkup(createElement(StandaloneInstallCard, {
    app: { slug: 'notes', name: 'Notes', updated_at: '1' },
    forceOpen: true,
  }))
  assert.match(successHtml, />Got it<\/button>/)
  assert.doesNotMatch(successHtml, /aria-label="Close"/)
})
