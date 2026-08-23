import assert from 'node:assert/strict'
import test from 'node:test'

import {
  drainCreatedChats,
  registerCreatedChats,
} from './_chatFixtureRegistry.mjs'
import { createTaggedChat } from './_chatTracker.mjs'

test('registry drains only exact IDs registered by one worker', () => {
  registerCreatedChats(3, ['chat-a', { id: 'chat-b' }, 'chat-a', null])
  registerCreatedChats(4, 'other-worker-chat')

  assert.deepEqual(drainCreatedChats(3), ['chat-a', 'chat-b'])
  assert.deepEqual(drainCreatedChats(3), [])
  assert.deepEqual(drainCreatedChats(4), ['other-worker-chat'])
})

test('tagged chat fixtures persist a model and simulate its provider boundary', async () => {
  const calls = []
  const routes = []
  const response = body => ({
    ok: () => true,
    json: async () => body,
    status: () => 200,
  })
  const page = {
    evaluate: async () => 'fixture-token',
    route: async (pattern, handler) => routes.push({ pattern, handler }),
    request: {
      post: async (url, options) => {
        calls.push({ method: 'POST', url, options })
        return response({ id: 'fixture-chat', title: 'Fixture chat' })
      },
      patch: async (url, options) => {
        calls.push({ method: 'PATCH', url, options })
        return response({ ok: true })
      },
    },
  }

  const chat = await createTaggedChat(page)

  assert.equal(chat.id, 'fixture-chat')
  assert.equal(routes.length, 1)
  assert.equal(routes[0].pattern, '**/api/auth/providers/status')
  assert.deepEqual(calls.map(call => call.method), ['POST', 'PATCH'])
  assert.deepEqual(calls[1].options.data, {
    agent_settings_json: { model: 'claude-sonnet-4-6' },
  })
})
