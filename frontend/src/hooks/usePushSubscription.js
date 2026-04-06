import { useEffect } from 'react'
import { apiFetch } from '../api/client.js'

/**
 * Subscribes the browser to Web Push notifications after login.
 * Runs once per session — re-subscribes each time (subscriptions can
 * rotate), but only prompts for permission once.
 */
export default function usePushSubscription() {
  useEffect(() => {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return

    async function subscribe() {
      try {
        const reg = await navigator.serviceWorker.ready

        // Fetch the VAPID public key from the server.
        const res = await apiFetch('/push/vapid-key')
        if (!res.ok) return
        const { publicKey } = await res.json()

        // Convert base64url to Uint8Array for subscribe().
        const padding = '='.repeat((4 - publicKey.length % 4) % 4)
        const raw = atob(publicKey.replace(/-/g, '+').replace(/_/g, '/') + padding)
        const key = new Uint8Array(raw.length)
        for (let i = 0; i < raw.length; i++) key[i] = raw.charCodeAt(i)

        // Subscribe (prompts for permission if needed).
        const sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: key,
        })

        // Send subscription to backend.
        const subJson = sub.toJSON()
        await apiFetch('/push/subscribe', {
          method: 'POST',
          body: JSON.stringify({
            endpoint: subJson.endpoint,
            keys: subJson.keys,
          }),
        })
      } catch {
        // Permission denied or push not supported — silently ignore.
      }
    }

    subscribe()
  }, [])
}
