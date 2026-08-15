/* Retire each Open-app shortcut five seconds after this chat first presents it. */

import { useEffect, useRef } from 'react'
import {
  OPEN_APP_CTA_AUTO_DISMISS_MS,
  shouldShowOpenAppCta,
} from '../chatRuntimeState.js'

function appBuildKey(app) {
  return `${app?.id ?? ''}:${app?.updated_at ?? ''}`
}

export default function useOpenAppCtaAutoDismiss({
  builtApps,
  turnActive,
  hidden,
  onDismissApp,
}, {
  setTimer = setTimeout,
  clearTimer = clearTimeout,
} = {}) {
  const timersRef = useRef(new Map())
  const onDismissRef = useRef(onDismissApp)
  onDismissRef.current = onDismissApp

  useEffect(() => {
    const timers = timersRef.current
    const eligibleApps = new Map(
      (Array.isArray(builtApps) ? builtApps : [])
        .filter(app => shouldShowOpenAppCta(app, turnActive))
        .map(app => [appBuildKey(app), app]),
    )

    // A click, acknowledgement, or replacement build retires the old timer.
    // Merely leaving the chat does not: once the shortcut was actually seen,
    // its five-second clock keeps its original meaning.
    for (const [key, entry] of timers) {
      if (eligibleApps.has(key)) continue
      clearTimer(entry.timerId)
      timers.delete(key)
    }

    // Hidden chats must not consume a shortcut the owner has never seen.
    if (hidden || typeof onDismissApp !== 'function') return

    for (const [key, app] of eligibleApps) {
      if (timers.has(key)) continue
      const timerId = setTimer(() => {
        const current = timersRef.current.get(key)
        if (!current || current.timerId !== timerId) return
        timersRef.current.delete(key)
        onDismissRef.current?.(current.app)
      }, OPEN_APP_CTA_AUTO_DISMISS_MS)
      timers.set(key, { timerId, app })
    }
  }, [builtApps, turnActive, hidden, onDismissApp, setTimer, clearTimer])

  useEffect(() => () => {
    for (const entry of timersRef.current.values()) {
      clearTimer(entry.timerId)
    }
    timersRef.current.clear()
  }, [clearTimer])
}
