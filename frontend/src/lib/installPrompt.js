/**
 * Captures the browser's one-shot PWA install prompt for later user action.
 *
 * Chromium can emit `beforeinstallprompt` while account setup is still on
 * screen, before the first-use card has mounted. App.jsx therefore starts
 * this module eagerly and the card subscribes to its small external-store
 * interface when it eventually appears.
 */

import { isStandaloneDisplay } from '../utils/installPlatform.js'

let captureStarted = false
let deferredPrompt = null
let installed = false
const listeners = new Set()

function emitChange() {
  for (const listener of listeners) listener()
}

export function startInstallPromptCapture(
  target = typeof window !== 'undefined' ? window : null,
) {
  if (!target || captureStarted) return
  captureStarted = true
  installed = isStandaloneDisplay(target)

  target.addEventListener('beforeinstallprompt', (event) => {
    if (installed) return
    event.preventDefault?.()
    deferredPrompt = event
    emitChange()
  })

  target.addEventListener('appinstalled', () => {
    deferredPrompt = null
    installed = true
    emitChange()
  })
}

export function getInstallPromptSnapshot() {
  if (installed) return 'installed'
  if (deferredPrompt) return 'ready'
  return 'manual'
}

export function subscribeInstallPrompt(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export async function requestInstall() {
  const promptEvent = deferredPrompt
  if (!promptEvent) return { outcome: 'unavailable' }

  // A BeforeInstallPromptEvent can only be used once. Clear it before
  // awaiting browser UI so a fast second tap cannot call prompt() twice.
  deferredPrompt = null
  emitChange()

  try {
    const promptResult = await promptEvent.prompt()
    const choice = typeof promptResult?.outcome === 'string'
      ? promptResult
      : await promptEvent.userChoice
    return {
      outcome: choice?.outcome === 'accepted' ? 'accepted' : 'dismissed',
    }
  } catch {
    return { outcome: 'unavailable' }
  }
}
