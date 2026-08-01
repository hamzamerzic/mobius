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
// Two different questions, deliberately kept apart.
//
// `launchedInstalled` — "does this document look like it is running AS an
// installed app?" Inferred from display mode at boot. Good enough to stop the
// product nagging someone to install what they are already using, and safe
// when wrong in that direction.
//
// `observedInstall` — "did the browser TELL us an install just happened?"
// Only `appinstalled` sets it. Nothing else may, because no browser on iOS
// answers "is this app on the home screen"; the in-app browser view iOS opens
// from a PWA even reports standalone display mode. Inferring installation
// there made the card congratulate people mid-install. A claim that specific
// needs evidence that specific.
let launchedInstalled = false
let observedInstall = false
const listeners = new Set()

function emitChange() {
  for (const listener of listeners) listener()
}

export function startInstallPromptCapture(
  target = typeof window !== 'undefined' ? window : null,
) {
  if (!target || captureStarted) return
  captureStarted = true
  launchedInstalled = isStandaloneDisplay(target)

  target.addEventListener('beforeinstallprompt', (event) => {
    if (launchedInstalled) return
    event.preventDefault?.()
    deferredPrompt = event
    emitChange()
  })

  target.addEventListener('appinstalled', () => {
    deferredPrompt = null
    observedInstall = true
    emitChange()
  })
}

export function getInstallPromptSnapshot() {
  if (launchedInstalled || observedInstall) return 'installed'
  if (deferredPrompt) return 'ready'
  return 'manual'
}

/**
 * True only when this page WATCHED an install complete. Use this — never the
 * snapshot above — to tell someone their app is on the home screen. The
 * snapshot answers "should we stop offering to install", which tolerates a
 * guess; this answers "did it work", which does not.
 */
export function getInstallObservedSnapshot() {
  return observedInstall
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
