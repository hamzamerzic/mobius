import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  PUSH_SW_SCOPE,
  PUSH_SW_URL,
  retireLegacySubscriptions,
  subscribeToPush,
} from '../pushSubscription.js'

// The shell PWA's manifest scope (frontend/public/manifest.webmanifest).
// Android hands a web push to the installed Möbius app only when the service
// worker's scope resolves to that WebAPK, and a WebAPK's intent filter carries
// this scope as its pathPrefix. A push worker registered outside it makes
// every notification a plain Chrome notification whose tap opens Chrome —
// invisible on desktop and in headless runs, so it is asserted here.
const SHELL_MANIFEST_SCOPE = '/shell/'

const ORIGIN = 'https://mobius.test'

function fakeSubscription(endpoint) {
  return {
    endpoint,
    unsubscribed: false,
    toJSON: () => ({ endpoint, keys: { p256dh: 'p', auth: 'a' } }),
    async unsubscribe() { this.unsubscribed = true },
  }
}

function fakeRegistration(scope, { subscription = null } = {}) {
  const created = []
  return {
    scope: `${ORIGIN}${scope}`,
    active: {},
    created,
    pushManager: {
      getSubscription: async () => subscription,
      subscribe: async (options) => {
        created.push(options)
        return fakeSubscription(`${ORIGIN}/endpoint${scope}`)
      },
    },
  }
}

function fakeContainer({ existing = [] } = {}) {
  const calls = []
  const pushWorker = fakeRegistration(PUSH_SW_SCOPE)
  return {
    calls,
    pushWorker,
    register: async (url, options) => {
      calls.push({ url, ...options })
      return pushWorker
    },
    getRegistrations: async () => [...existing, pushWorker],
  }
}

function recordingPush() {
  const push = {
    sent: [],
    removed: [],
    vapidKey: async () => ({
      ok: true,
      json: async () => ({ publicKey: 'QUJD' }),
    }),
    subscribe: async (payload) => { push.sent.push(payload) },
    unsubscribe: async (payload) => { push.removed.push(payload) },
  }
  return push
}

test('the push worker is registered inside the shell PWA scope', async () => {
  const container = fakeContainer()
  await subscribeToPush({ container, push: recordingPush() })

  assert.deepEqual(container.calls, [
    { url: PUSH_SW_URL, scope: PUSH_SW_SCOPE },
  ])
  assert.ok(
    PUSH_SW_SCOPE.startsWith(SHELL_MANIFEST_SCOPE),
    `${PUSH_SW_SCOPE} must sit inside the shell scope ${SHELL_MANIFEST_SCOPE}`,
  )
})

test('the push scope holds no documents, so it claims no shell pages', () => {
  // Registering at the manifest scope itself would out-match the `/`-scoped
  // caching worker for the shell's own pages, take control of them, and
  // disable the shell precache.
  assert.notEqual(PUSH_SW_SCOPE, SHELL_MANIFEST_SCOPE)
  assert.ok(PUSH_SW_SCOPE.endsWith('/'), 'a scope prefix must end in /')
})

test('the subscription is created on the push worker and sent to the server',
  async () => {
    const caching = fakeRegistration('/')
    const container = fakeContainer({ existing: [caching] })
    const push = recordingPush()

    await subscribeToPush({ container, push })

    assert.equal(caching.created.length, 0, 'never subscribes on the cache SW')
    assert.equal(container.pushWorker.created.length, 1)
    assert.equal(container.pushWorker.created[0].userVisibleOnly, true)
    assert.deepEqual(push.sent, [{
      endpoint: `${ORIGIN}/endpoint${PUSH_SW_SCOPE}`,
      keys: { p256dh: 'p', auth: 'a' },
    }])
  })

test('a subscription left on the caching worker is retired', async () => {
  // sw.js no longer handles `push`, so a send to its endpoint would trip the
  // browser's userVisibleOnly fallback ("site updated in the background").
  const stale = fakeSubscription(`${ORIGIN}/endpoint-legacy`)
  const caching = fakeRegistration('/', { subscription: stale })
  const container = fakeContainer({ existing: [caching] })
  const push = recordingPush()

  await subscribeToPush({ container, push })

  assert.deepEqual(push.removed, [{ endpoint: `${ORIGIN}/endpoint-legacy` }])
  assert.equal(stale.unsubscribed, true)
})

test('the freshly created subscription is never retired', async () => {
  // The push worker's own registration is skipped by scope, but guard the
  // endpoint too: retiring what we just registered would silence push.
  const endpoint = `${ORIGIN}/endpoint${PUSH_SW_SCOPE}`
  const sameEndpoint = fakeRegistration('/', {
    subscription: fakeSubscription(endpoint),
  })
  const container = fakeContainer({ existing: [sameEndpoint] })
  const push = recordingPush()

  await subscribeToPush({ container, push })

  assert.deepEqual(push.removed, [])
})

test('a registration without push support is skipped, not fatal', async () => {
  const broken = {
    scope: `${ORIGIN}/apps/example/`,
    pushManager: { getSubscription: async () => { throw new Error('denied') } },
  }
  const stale = fakeSubscription(`${ORIGIN}/endpoint-legacy`)
  const caching = fakeRegistration('/', { subscription: stale })
  const container = fakeContainer({ existing: [broken, caching] })
  const push = recordingPush()

  await retireLegacySubscriptions(container, `${ORIGIN}/current`, push)

  assert.deepEqual(push.removed, [{ endpoint: `${ORIGIN}/endpoint-legacy` }])
})
