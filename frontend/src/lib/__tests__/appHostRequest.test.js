import test from 'node:test'
import assert from 'node:assert/strict'

import { appHostRequest } from '../appHostRequest.js'

test('app host requests expose only the reviewed navigation contract', () => {
  assert.deepEqual(appHostRequest({
    type: 'moebius:new-chat', draft: 'hello', autoSend: 1, secret: 'drop-me',
  }), {
    type: 'moebius:new-chat', draft: 'hello', autoSend: false,
  })
  assert.deepEqual(appHostRequest({
    type: 'moebius:open-app', appId: 'atlas', intent: 'setup', extra: true,
  }), {
    type: 'moebius:open-app', appId: 'atlas', intent: 'setup',
  })
  assert.equal(appHostRequest({ type: 'moebius:open-chat', chatId: '' }), null)
  assert.equal(appHostRequest({ type: 'unexpected', appId: 1 }), null)
})

test('chat controls retain only a correlated status or stop request', () => {
  assert.deepEqual(appHostRequest({
    type: 'moebius:chat-control',
    requestId: 'chat-control:abc:1',
    action: 'stop',
    chatId: ' chat-123 ',
    ownerToken: 'nope',
  }), {
    type: 'moebius:chat-control',
    requestId: 'chat-control:abc:1',
    action: 'stop',
    chatId: 'chat-123',
  })
  assert.equal(appHostRequest({
    type: 'moebius:chat-control', requestId: 'bad', action: 'status', chatId: '1',
  }), null)
  assert.equal(appHostRequest({
    type: 'moebius:chat-control', requestId: 'chat-control:abc:2', action: 'delete', chatId: '1',
  }), null)
})
