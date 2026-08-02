import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  chatDetailCacheValue,
  chatSnapshotMatchesRuntime,
  mergeChatDetailCacheValue,
  mergeRecentMessagesIntoLoadedWindow,
  messageKey,
  messageMatchesKey,
} from '../../../lib/chatDetailCache.js'

test('message row addresses remain stable across authoritative replacements', () => {
  assert.equal(messageKey({ id: 'message-1', role: 'user', ts: 10 }, 4), 'message-1')
  assert.equal(messageKey({ id: 7 }, 4), '7')
  assert.equal(messageKey({ cid: 'client-1', role: 'user', ts: 10 }, 4), 'client-1')
  assert.equal(messageKey({ role: 'assistant', ts: 10 }, 4), 'assistant-10')
  assert.equal(messageKey({ role: 'assistant' }, 4), 'assistant-4')
  const replaced = { id: 'server-1', cid: 'client-1', role: 'user', ts: 10 }
  assert.equal(messageMatchesKey(replaced, 4, 'server-1'), true)
  assert.equal(messageMatchesKey(replaced, 4, 'client-1'), true)
  assert.equal(messageMatchesKey(replaced, 4, 'user-10'), true)
  assert.equal(messageMatchesKey(replaced, 4, 'user-4'), true)
  assert.equal(messageMatchesKey(replaced, 4, 'assistant-10'), false)
})

test('prefetched chat detail matches the synchronous ChatView cache contract', () => {
  const source = {
    updated_at: '2026-07-30T12:00:00Z',
    messages: [{
      role: 'assistant',
      blocks: [{ type: 'tool', status: 'running' }, { type: 'text', text: 'done' }],
    }],
    offset: 12,
    running: false,
    active_goal_objective: 'Finish the migration',
    pending_messages: [{ id: 'queued' }],
    pending_question_id: 'question-1',
    provider: 'codex',
    created_by_app_id: 7,
    agent_settings_json: { model: 'example' },
    effective_agent_settings: { effort: 'high' },
    has_assistant_turns: true,
    auto_resume_on_limit: true,
    auto_resume_on_restart: false,
  }

  const cached = chatDetailCacheValue(source)

  assert.equal(cached.messages[0].blocks[0].status, 'done')
  assert.equal(cached.updated_at, source.updated_at)
  assert.equal(source.messages[0].blocks[0].status, 'running', 'projection does not mutate the response')
  assert.equal(cached.offset, 12)
  assert.equal(cached.activeGoalObjective, 'Finish the migration')
  assert.equal(cached.pending_question_id, 'question-1')
  assert.deepEqual(cached.chatInfo, {
    provider: 'codex',
    created_by_app_id: 7,
    agent_settings_json: { model: 'example' },
    effective: { effort: 'high' },
    has_assistant_turns: true,
    auto_resume_on_limit: true,
    auto_resume_on_restart: false,
  })
})

test('a retained snapshot is reusable only at the same explicit row version', () => {
  const cached = { updated_at: '2026-07-30T12:00:00Z' }
  assert.equal(chatSnapshotMatchesRuntime(cached, {
    updated_at: '2026-07-30T12:00:00Z',
  }), true)
  assert.equal(chatSnapshotMatchesRuntime(cached, {
    updated_at: '2026-07-30T12:00:01Z',
  }), false)
  assert.equal(chatSnapshotMatchesRuntime(cached, {}), false)
  assert.equal(chatSnapshotMatchesRuntime({}, {
    updated_at: '2026-07-30T12:00:00Z',
  }), false)
})

test('a tail refresh retains every verified older row needed by a saved address', () => {
  const loaded = Array.from({ length: 40 }, (_, index) => ({
    id: `message-${index + 5}`,
    content: `Loaded ${index + 5}`,
  }))
  const recent = Array.from({ length: 20 }, (_, index) => ({
    id: `message-${index + 25}`,
    content: `Fresh ${index + 25}`,
  }))
  const merged = mergeRecentMessagesIntoLoadedWindow({
    loadedMessages: loaded,
    loadedOffset: 5,
    recentMessages: recent,
    recentOffset: 25,
  })
  assert.equal(merged.offset, 5)
  assert.equal(merged.messages.length, 40)
  assert.equal(merged.messages[0].content, 'Loaded 5')
  assert.equal(merged.messages[20].content, 'Fresh 25')
})

test('background detail publication keeps the full loaded window and new version', () => {
  const current = {
    updated_at: 'old',
    offset: 0,
    messages: Array.from({ length: 30 }, (_, id) => ({ id: String(id) })),
  }
  const recent = {
    updated_at: 'new',
    offset: 20,
    messages: Array.from({ length: 11 }, (_, index) => ({
      id: String(index + 20),
      content: 'fresh',
    })),
  }
  const merged = mergeChatDetailCacheValue(current, recent)
  assert.equal(merged.updated_at, 'new')
  assert.equal(merged.offset, 0)
  assert.equal(merged.messages.length, 31)
  assert.equal(merged.messages[0].id, '0')
  assert.equal(merged.messages.at(-1).id, '30')
})

test('an unverifiable background tail never destroys the restoration window', () => {
  const current = {
    updated_at: 'old',
    offset: 0,
    messages: Array.from({ length: 20 }, (_, index) => ({ id: `old-${index}` })),
  }
  const recent = {
    updated_at: 'new',
    offset: 40,
    messages: Array.from({ length: 20 }, (_, index) => ({ id: `new-${index}` })),
  }
  const merged = mergeChatDetailCacheValue(current, recent)
  assert.equal(merged.updated_at, null, 'next activation must revalidate by saved anchor')
  assert.equal(merged.offset, 0)
  assert.equal(merged.messages, current.messages)
})
