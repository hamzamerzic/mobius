import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  streamSnapshotKey,
  readStoredStreamSnapshot,
  writeStoredStreamSnapshot,
  clearStoredStreamSnapshot,
  reclaimStoredStreamSnapshots,
} from '../streamSnapshotCache.js'

function makeStorage() {
  const map = new Map()
  const calls = { set: 0 }
  return {
    map,
    calls,
    get length() { return map.size },
    key(index) { return [...map.keys()][index] ?? null },
    getItem(key) { return map.has(key) ? map.get(key) : null },
    setItem(key, value) { calls.set += 1; map.set(key, value) },
    removeItem(key) { map.delete(key) },
  }
}

test('stream snapshots keep assistant identity and ignore empty reconnect state', () => {
  const storage = makeStorage()
  const items = [{ type: 'text', content: 'partial' }]
  const snapshot = { items, assistantMessageId: 'assistant-1' }

  writeStoredStreamSnapshot('chat-a', snapshot, storage)
  writeStoredStreamSnapshot('chat-a', { items: [] }, storage)

  assert.deepEqual(readStoredStreamSnapshot('chat-a', storage), snapshot)
  assert.equal(storage.map.has(streamSnapshotKey('chat-a')), true)
  assert.equal(storage.calls.set, 1)
})

test('clear removes the current snapshot', () => {
  const storage = makeStorage()
  writeStoredStreamSnapshot('chat-a', {
    items: [{ type: 'text', content: 'new' }],
    assistantMessageId: 'assistant-2',
  }, storage)

  clearStoredStreamSnapshot('chat-a', storage)

  assert.equal(storage.map.has(streamSnapshotKey('chat-a')), false)
})

test('quota reclamation drops only regenerable stream snapshots', () => {
  const storage = makeStorage()
  storage.setItem('draft:chat-a', 'owner data')
  storage.setItem(streamSnapshotKey('running-chat'), '{"items":[{"type":"text"}]}')
  storage.setItem('chat-stream-items:v2:old-chat', '[{"type":"text"}]')

  assert.equal(reclaimStoredStreamSnapshots(storage), 2)
  assert.equal(storage.getItem('draft:chat-a'), 'owner data')
  assert.equal(storage.getItem(streamSnapshotKey('running-chat')), null)
})

test('read returns an empty identity-bearing state for corrupt or absent values', () => {
  const storage = makeStorage()
  storage.setItem(streamSnapshotKey('bad'), '{nope')

  const empty = { items: [], assistantMessageId: null }
  assert.deepEqual(readStoredStreamSnapshot('missing', storage), empty)
  assert.deepEqual(readStoredStreamSnapshot('bad', storage), empty)
})

test('default cache is optional when an opaque sandbox denies sessionStorage', () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    get() { throw new DOMException('Blocked by opaque sandbox', 'SecurityError') },
  })
  try {
    assert.deepEqual(readStoredStreamSnapshot('chat-a'), {
      items: [], assistantMessageId: null,
    })
    assert.doesNotThrow(() => writeStoredStreamSnapshot('chat-a', {
      items: [{ type: 'text' }], assistantMessageId: 'assistant-3',
    }))
    assert.doesNotThrow(() => clearStoredStreamSnapshot('chat-a'))
  } finally {
    if (descriptor) Object.defineProperty(globalThis, 'sessionStorage', descriptor)
    else delete globalThis.sessionStorage
  }
})
