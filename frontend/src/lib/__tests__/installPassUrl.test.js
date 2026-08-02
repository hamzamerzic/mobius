import assert from 'node:assert/strict'
import { test } from 'node:test'

import { readInstallPass, withoutInstallPass } from '../installPassUrl.js'

test('only a standalone app reads the install pass', () => {
  assert.equal(readInstallPass('?install=1&pass=opaque', { slug: 'notes' }), 'opaque')
  assert.equal(readInstallPass('?install=1&pass=opaque', null), '')
  assert.equal(readInstallPass('%broken', { slug: 'notes' }), '')
})

test('URL cleanup removes only the one-time pass', () => {
  assert.equal(
    withoutInstallPass('https://mobius.test/apps/notes/?install=1&pass=opaque#card'),
    '/apps/notes/?install=1#card',
  )
  assert.equal(withoutInstallPass('not a URL'), null)
})
