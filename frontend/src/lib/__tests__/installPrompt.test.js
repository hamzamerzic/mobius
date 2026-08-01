/**
 * Unit tests for the early PWA install-prompt capture.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

async function freshModule() {
  return import(new URL(`../installPrompt.js?t=${Math.random()}`, import.meta.url))
}

function makeTarget({ standalone = false } = {}) {
  const handlers = new Map()
  return {
    navigator: { standalone: false },
    matchMedia: () => ({ matches: standalone }),
    addEventListener(type, handler) {
      handlers.set(type, handler)
    },
    dispatch(type, event = {}) {
      handlers.get(type)?.(event)
    },
  }
}

test('captures and consumes a one-shot native install prompt', async () => {
  const installPrompt = await freshModule()
  const target = makeTarget()
  let prevented = false
  let promptCalls = 0
  installPrompt.startInstallPromptCapture(target)

  target.dispatch('beforeinstallprompt', {
    preventDefault() { prevented = true },
    async prompt() {
      promptCalls += 1
      return { outcome: 'accepted' }
    },
  })

  assert.equal(prevented, true)
  assert.equal(installPrompt.getInstallPromptSnapshot(), 'ready')
  assert.deepEqual(await installPrompt.requestInstall(), { outcome: 'accepted' })
  assert.equal(promptCalls, 1)
  assert.equal(installPrompt.getInstallPromptSnapshot(), 'manual')
  assert.deepEqual(await installPrompt.requestInstall(), { outcome: 'unavailable' })
  assert.equal(promptCalls, 1)
})

test('falls back to userChoice for older Chromium prompt results', async () => {
  const installPrompt = await freshModule()
  const target = makeTarget()
  installPrompt.startInstallPromptCapture(target)
  target.dispatch('beforeinstallprompt', {
    preventDefault() {},
    async prompt() {},
    userChoice: Promise.resolve({ outcome: 'dismissed' }),
  })

  assert.deepEqual(await installPrompt.requestInstall(), { outcome: 'dismissed' })
})

test('appinstalled and standalone launch suppress the install invitation', async () => {
  const captured = await freshModule()
  const target = makeTarget()
  captured.startInstallPromptCapture(target)
  target.dispatch('appinstalled')
  assert.equal(captured.getInstallPromptSnapshot(), 'installed')

  const standalone = await freshModule()
  standalone.startInstallPromptCapture(makeTarget({ standalone: true }))
  assert.equal(standalone.getInstallPromptSnapshot(), 'installed')
})

test('subscribers are notified when prompt availability changes', async () => {
  const installPrompt = await freshModule()
  const target = makeTarget()
  let changes = 0
  installPrompt.startInstallPromptCapture(target)
  const unsubscribe = installPrompt.subscribeInstallPrompt(() => { changes += 1 })

  target.dispatch('beforeinstallprompt', {
    preventDefault() {},
    async prompt() { return { outcome: 'dismissed' } },
  })
  await installPrompt.requestInstall()
  unsubscribe()
  target.dispatch('appinstalled')

  assert.equal(changes, 2)
})

// iOS reports standalone display mode inside the in-app browser it opens from
// an installed PWA — a page that is plainly not the installed app. That guess
// is fine for suppressing an install offer and catastrophic for announcing
// success: it told someone mid-install that their app was already added.
test('a standalone-looking launch suppresses the offer but claims nothing', async () => {
  const installPrompt = await freshModule()
  installPrompt.startInstallPromptCapture(makeTarget({ standalone: true }))

  assert.equal(installPrompt.getInstallPromptSnapshot(), 'installed')
  assert.equal(installPrompt.getInstallObservedSnapshot(), false)
})

test('only a witnessed appinstalled event may be announced', async () => {
  const installPrompt = await freshModule()
  const target = makeTarget()
  installPrompt.startInstallPromptCapture(target)

  assert.equal(installPrompt.getInstallObservedSnapshot(), false)
  target.dispatch('appinstalled')
  assert.equal(installPrompt.getInstallObservedSnapshot(), true)
  assert.equal(installPrompt.getInstallPromptSnapshot(), 'installed')
})

test('subscribers are notified when an install is witnessed', async () => {
  const installPrompt = await freshModule()
  const target = makeTarget()
  installPrompt.startInstallPromptCapture(target)
  let notified = 0
  installPrompt.subscribeInstallPrompt(() => { notified += 1 })

  target.dispatch('appinstalled')
  assert.equal(notified, 1)
  assert.equal(installPrompt.getInstallObservedSnapshot(), true)
})
