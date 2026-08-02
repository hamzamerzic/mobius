import { test } from 'node:test'
import assert from 'node:assert/strict'

import { overlayAcceptedChatDetail } from './_mockAcceptedMessages.mjs'

test('accepted rows recompute an anchor response after the persistence overlay', () => {
  const accepted = [{
    role: 'user',
    ts: 2000,
    cid: 'accepted-client-id',
    content: 'Accepted but not persisted yet',
  }]
  const detail = {
    messages: [{ id: 'persisted-tail', role: 'assistant', ts: 1000 }],
    offset: 4,
    total: 5,
    requested_anchor_found: false,
  }

  const overlaid = overlayAcceptedChatDetail(
    detail,
    accepted,
    'http://mobius.test/api/chats/chat-1?limit=20&anchor=accepted-client-id',
  )

  assert.equal(overlaid.requested_anchor_found, true)
  assert.equal(overlaid.offset, 5)
  assert.equal(overlaid.total, 6)
  assert.deepEqual(overlaid.messages, accepted)
})

test('a genuinely absent overlay anchor returns the bounded recent window', () => {
  const messages = Array.from({ length: 25 }, (_, index) => ({
    id: `message-${index}`,
    role: 'assistant',
    ts: index,
  }))

  const overlaid = overlayAcceptedChatDetail(
    { messages, offset: 10, total: 35, requested_anchor_found: false },
    [],
    'http://mobius.test/api/chats/chat-1?limit=7&anchor=missing',
  )

  assert.equal(overlaid.requested_anchor_found, false)
  assert.equal(overlaid.offset, 28)
  assert.equal(overlaid.messages.length, 7)
  assert.equal(overlaid.messages[0].id, 'message-18')
})
