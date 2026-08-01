import assert from 'node:assert/strict'
import { test } from 'node:test'

import { loginBoundaryPath, safeReturnPath } from '../safeReturnPath.js'

const ORIGIN = 'https://mobius.example'

test('safe return paths preserve same-origin path, query, and hash', () => {
  assert.equal(
    safeReturnPath('/apps/demo/?x=1#section', ORIGIN),
    '/apps/demo/?x=1#section',
  )
  assert.equal(
    safeReturnPath('/hello%20world?raw=%#still-%', ORIGIN),
    '/hello%20world?raw=%#still-%',
  )
})

test('malformed pathname escapes are rejected without throwing', () => {
  for (const path of ['/%', '/%2', '/%GG', '/%E0%A4%A']) {
    assert.doesNotThrow(() => safeReturnPath(path, ORIGIN))
    assert.equal(safeReturnPath(path, ORIGIN), null)
  }
})

test('return paths reject cross-origin and backslash forms', () => {
  for (const path of [
    null,
    42,
    'apps/demo',
    'https://evil.example/path',
    '//evil.example/path',
    '/\\evil',
    '/%5cevil',
    '/%5Cevil',
  ]) {
    assert.equal(safeReturnPath(path, ORIGIN), null)
  }
})

test('double-encoded backslashes retain the existing normalization policy', () => {
  assert.equal(safeReturnPath('/%255cstill-encoded', ORIGIN), '/%255cstill-encoded')
})

test('login boundary preserves a complete install target as one return value', () => {
  const target = '/apps/notes/?install=1&pass=opaque#install'
  const boundary = new URL(loginBoundaryPath(target), ORIGIN)
  assert.equal(boundary.pathname, '/')
  assert.equal(boundary.searchParams.get('return'), target)
})
