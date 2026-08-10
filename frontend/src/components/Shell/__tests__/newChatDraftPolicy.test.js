import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  newChatCandidateResolution,
  reconcileHydratedNewChatCandidate,
  standardNewChatCandidate,
} from '../newChatPolicy.js'

const empty = (id, extra = {}) => ({
  id,
  has_messages: false,
  running: false,
  ...extra,
})

test('standard mode resumes the most recently left local draft chat', () => {
  const chats = [
    empty('older-draft'),
    empty('newer-draft'),
    empty('no-draft'),
    empty('now-running', { running: true }),
  ]
  const candidate = standardNewChatCandidate(chats, [
    { chatId: 'now-running', input: 'newest but active elsewhere', attachments: [] },
    { chatId: 'newer-draft', input: 'keep this', attachments: [] },
    { chatId: 'older-draft', input: 'older', attachments: [] },
  ], {
    activeChatId: 'reading-chat',
  })

  assert.deepEqual(candidate, {
    chatId: 'newer-draft',
    source: 'draft',
    draft: { chatId: 'newer-draft', input: 'keep this', attachments: [] },
  })
})

test('the visible untouched blank outranks an older Standard draft', () => {
  const active = empty('active-blank')
  const olderDraft = empty('older-draft')
  const candidate = standardNewChatCandidate([active, olderDraft], [
    { chatId: 'older-draft', input: 'keep this', attachments: [] },
  ], {
    activeChatId: 'active-blank',
  })

  assert.deepEqual(candidate, {
    chatId: 'active-blank',
    source: 'active',
    draft: null,
  })
})

test('draft resume never borrows a populated, recovered, or streaming chat', () => {
  const chats = [
    empty('populated', { has_messages: true }),
    empty('recovered'),
    empty('streaming'),
  ]
  const drafts = chats.map(chat => ({
    chatId: chat.id, input: 'draft', attachments: [],
  }))
  assert.equal(standardNewChatCandidate(chats, drafts, {
    activeChatId: 'reading-chat',
    recoveredChatIds: new Set(['recovered']),
    streamingChatIds: new Set(['streaming']),
  }), null)
})

test('an active blank with a draft carries its complete resume snapshot', () => {
  const active = empty('active')
  const draft = {
    chatId: 'active',
    input: 'unfinished',
    attachments: [{ name: 'reference.png', status: 'done' }],
  }
  assert.deepEqual(standardNewChatCandidate([active], [draft], {
    activeChatId: 'active',
  }), {
    chatId: 'active',
    source: 'draft',
    draft,
  })
})

test('candidate provenance owns offline reuse and authoritative probing', () => {
  const active = { chatId: 'active', source: 'active', draft: null }
  const draft = { chatId: 'draft', source: 'draft', draft: { input: 'keep' } }
  const history = { chatId: 'history', source: 'history', draft: null }

  assert.equal(newChatCandidateResolution(active, { online: false }), 'reuse')
  assert.equal(newChatCandidateResolution(active, { online: true }), 'probe')
  assert.equal(newChatCandidateResolution(draft, { online: false }), 'reuse')
  assert.equal(newChatCandidateResolution(draft, { online: true }), 'reuse')
  assert.equal(newChatCandidateResolution(history, { online: false }), 'reject')
  assert.equal(newChatCandidateResolution(history, { online: true }), 'probe')
})

test('late durable discovery never guesses a merge over early fresh typing', () => {
  const active = { chatId: 'active', source: 'active', draft: null }
  const durable = {
    chatId: 'durable',
    source: 'draft',
    draft: { input: 'older thought', attachments: [] },
  }
  assert.deepEqual(reconcileHydratedNewChatCandidate(active, durable, {
    leaseWasEdited: true,
  }), {
    candidate: active,
    primeLease: false,
  })
  assert.deepEqual(reconcileHydratedNewChatCandidate(active, {
    ...durable,
    chatId: 'active',
  }, { leaseWasEdited: true }), {
    candidate: null,
    primeLease: false,
  })
  assert.deepEqual(reconcileHydratedNewChatCandidate(null, durable, {
    leaseWasEdited: true,
  }), {
    candidate: null,
    primeLease: false,
  })
  assert.deepEqual(reconcileHydratedNewChatCandidate(active, active, {
    leaseWasEdited: true,
  }), {
    candidate: active,
    primeLease: false,
  })
  assert.deepEqual(reconcileHydratedNewChatCandidate(null, durable), {
    candidate: durable,
    primeLease: true,
  })
})
