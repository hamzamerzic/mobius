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

test('stream snapshots use the v2 key and ignore empty reconnect state', () => {
  const storage = makeStorage()
  const items = [{ type: 'text', content: 'partial' }]

  writeStoredStreamSnapshot('chat-a', items, storage)
  writeStoredStreamSnapshot('chat-a', [], storage)

  assert.deepEqual(readStoredStreamSnapshot('chat-a', storage), items)
  assert.equal(storage.map.has(streamSnapshotKey('chat-a')), true)
  assert.equal(storage.calls.set, 1)
})

test('clear removes the current snapshot', () => {
  const storage = makeStorage()
  writeStoredStreamSnapshot('chat-a', [{ type: 'text', content: 'new' }], storage)

  clearStoredStreamSnapshot('chat-a', storage)

  assert.equal(storage.map.has(streamSnapshotKey('chat-a')), false)
})

test('quota reclamation drops only regenerable stream snapshots', () => {
  const storage = makeStorage()
  storage.setItem('draft:chat-a', 'owner data')
  storage.setItem(streamSnapshotKey('running-chat'), '[{"type":"text"}]')

  assert.equal(reclaimStoredStreamSnapshots(storage), 1)
  assert.equal(storage.getItem('draft:chat-a'), 'owner data')
  assert.equal(storage.getItem(streamSnapshotKey('running-chat')), null)
})

test('read returns [] for corrupt or absent values', () => {
  const storage = makeStorage()
  storage.setItem(streamSnapshotKey('bad'), '{nope')

  assert.deepEqual(readStoredStreamSnapshot('missing', storage), [])
  assert.deepEqual(readStoredStreamSnapshot('bad', storage), [])
})

test('default cache is optional when an opaque sandbox denies sessionStorage', () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    get() { throw new DOMException('Blocked by opaque sandbox', 'SecurityError') },
  })
  try {
    assert.deepEqual(readStoredStreamSnapshot('chat-a'), [])
    assert.doesNotThrow(() => writeStoredStreamSnapshot('chat-a', [{ type: 'text' }]))
    assert.doesNotThrow(() => clearStoredStreamSnapshot('chat-a'))
  } finally {
    if (descriptor) Object.defineProperty(globalThis, 'sessionStorage', descriptor)
    else delete globalThis.sessionStorage
  }
})
