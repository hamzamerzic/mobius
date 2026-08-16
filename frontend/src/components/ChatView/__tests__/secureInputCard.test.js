import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import SecureInputCard from '../SecureInputCard.jsx'


const fields = [
  {
    name: 'username',
    label: 'Username',
    type: 'text',
    autocomplete: 'username',
  },
  {
    name: 'password',
    label: 'Password',
    type: 'password',
    autocomplete: 'current-password',
  },
]


function renderCard(overrides = {}, interactive = false) {
  const block = {
    type: 'secure_input',
    request_id: 'request-1',
    mode: 'sealed',
    title: 'Private connection',
    description: 'Values bypass model context.',
    fields,
    status: 'pending',
    ...overrides,
  }
  return renderToStaticMarkup(createElement(SecureInputCard, {
    block,
    chatId: 'chat-1',
    interactive,
  }))
}


test('pending secure input renders one uncontrolled field per prompt', () => {
  const html = renderCard({}, true)

  assert.equal((html.match(/<input/g) || []).length, 2)
  assert.match(html, /name="username"/)
  assert.match(html, /name="password"/)
  assert.match(html, /type="password"/)
  assert.match(html, /data-chat-inline-editor="secure-input"/)
  assert.match(html, />Enter securely</)
  assert.match(html, /values bypass the chat and AI/)
  assert.doesNotMatch(html, /value=/)
})


test('settled secure input renders locked prompt receipts without fields', () => {
  const html = renderCard({ status: 'completed' })

  assert.match(html, />Private connection</)
  assert.match(html, />Username</)
  assert.match(html, />Password</)
  assert.equal((html.match(/Provided securely/g) || []).length, 2)
  assert.equal((html.match(/secure-card__receipt-lock/g) || []).length, 2)
  assert.match(html, /Receipt saved · entered values omitted/)
  assert.doesNotMatch(html, /<input/)
})


test('failed and expired receipts use non-success status copy', () => {
  assert.equal(
    (renderCard({ status: 'failed' }).match(/Not used/g) || []).length,
    2,
  )
  assert.equal(
    (renderCard({ status: 'expired' }).match(/Not provided/g) || []).length,
    2,
  )
})


test('reveal mode is visually distinct and requires explicit confirmation', () => {
  const html = renderCard({ mode: 'reveal' }, true)

  assert.match(html, /secure-card--reveal/)
  assert.match(html, /name="reveal_confirmed"/)
  assert.match(html, /sent to the AI provider/)
  assert.match(html, />Reveal for this turn</)
})
