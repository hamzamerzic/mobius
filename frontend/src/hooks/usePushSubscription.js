import { useEffect } from 'react'
import { subscribeToPush } from '../lib/pushSubscription.js'

/**
 * Subscribes the browser to Web Push notifications after login.
 * Runs once per session — re-subscribes each time (subscriptions can
 * rotate), but only prompts for permission once.
 *
 * Push lives on its own service worker — see `lib/pushSubscription.js`.
 */
export default function usePushSubscription() {
  useEffect(() => {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return
    // A denied permission can never be re-raised from here, so the whole
    // pipeline (worker install, key fetch, subscribe) would be wasted. Only
    // 'denied' short-circuits: 'default' is what raises the prompt.
    if (Notification?.permission === 'denied') return
    // Push unsupported or the prompt refused — nothing to surface.
    subscribeToPush().catch(() => {})
  }, [])
}
