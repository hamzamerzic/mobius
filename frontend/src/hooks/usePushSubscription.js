import { useEffect } from 'react'
import { subscribeToPush } from '../lib/pushSubscription.js'

/**
 * Subscribes the browser to Web Push notifications after login.
 * Runs once per session — re-subscribes each time (subscriptions can
 * rotate), but only prompts for permission once.
 *
 * The subscription deliberately lives on its own service worker rather than
 * the shell's caching worker; `lib/pushSubscription.js` explains why that
 * decides whether an Android notification opens Möbius or Chrome.
 */
export default function usePushSubscription() {
  useEffect(() => {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return
    // Permission denied or push unsupported — nothing to surface.
    subscribeToPush().catch(() => {})
  }, [])
}
