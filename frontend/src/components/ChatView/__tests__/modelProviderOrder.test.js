import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { PROVIDER_ORDER, PROVIDER_INFO } from '../providerRegistry.jsx'

test('the app-owned Möbius subscription follows the connected coding subscriptions', () => {
  assert.deepEqual(PROVIDER_ORDER, ['codex', 'claude', 'mobius'])
})

test('every ordered provider carries product-facing metadata and Möbius reads as a subscription', () => {
  for (const id of PROVIDER_ORDER) {
    const info = PROVIDER_INFO[id]
    assert.ok(info, `${id} has provider metadata`)
    assert.equal(typeof info.label, 'string')
    assert.equal(typeof info.Logo, 'function')
  }
  assert.equal(PROVIDER_INFO.mobius.label, 'Möbius subscription')
  // The trial is activated silently on sign-in; the picker never brands
  // the app-owned provider as a "trial".
  for (const info of Object.values(PROVIDER_INFO)) {
    assert.notEqual(info.label, 'Möbius trial')
  }
})

test('the Möbius mark renders as the shared ink glyph, not an inlined provider path', () => {
  const markup = renderToStaticMarkup(createElement(PROVIDER_INFO.mobius.Logo))
  assert.match(markup, /class="csp__mobius-logo"/)
  // No inlined OpenAI path leaks into the Möbius glyph.
  assert.doesNotMatch(markup, /M8\.2 7\.2c-2\.9/)
})
