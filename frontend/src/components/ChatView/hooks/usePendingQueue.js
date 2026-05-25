import { useState, useRef, useCallback } from 'react'

/**
 * Hook that owns the per-chat pending-message queue (the items shown
 * in the queued-tray above the composer) and ALL the legitimate
 * mutations against it. Encapsulates the setState/ref-mirror dance
 * that previously lived inline in ChatView.jsx at eight separate
 * call sites, the natural drift between which is the bug class
 * this hook exists to prevent.
 *
 * @template {object} PendingMsg
 *
 * Pending message shape (carried unchanged from the prior inline
 * code; persisted to the server only as {role, content, ts,
 * attachments?}):
 *   - role:        always 'user'
 *   - content:     string
 *   - ts:          number (epoch ms; server-assigned after POST, or
 *                  optimistic Date.now() until then)
 *   - cid:         string (stable client-side React key; survives
 *                  optimistic-ts -> server-ts swap so QueuedMessages
 *                  doesn't remount under a new key and lose UI state)
 *   - queued:      true (marker)
 *   - position?:   number (server-assigned)
 *   - attachments?: array
 *
 * Critical contract: pendingMessagesRef.current MUST update
 * SYNCHRONOUSLY on every mutation. handleStop's
 * fetchGenRef.current++ / pendingMessagesRef.current = [] sequence
 * runs BEFORE the await on /chat/stop; if any mutation here only
 * scheduled a render, the natural onStreamEnd handler could read
 * stale ref contents and re-fire fetchMessages({force:true}),
 * overwriting the just-promoted partial. R1 in _034-design.md
 * spells out the failure mode.
 *
 * The `setPendingMessages` setter is intentionally NOT exposed —
 * the five named operations cover every call site enumerated in
 * the design and forcing them through the API is the encapsulation.
 *
 * @returns {{
 *   pendingMessages: PendingMsg[],
 *   pendingMessagesRef: React.MutableRefObject<PendingMsg[]>,
 *   add: (msg: PendingMsg) => void,
 *   swapOptimisticTs: (cid: string, serverTs: number, position?: number) => void,
 *   promoteByTs: (ts: number) => PendingMsg | null,
 *   cancelByTs: (ts: number) => void,
 *   hydrate: (serverList: Array<{ts: number, content: string, role?: string, attachments?: Array, position?: number}>) => void,
 *   clear: () => void,
 * }}
 */
export default function usePendingQueue() {
  const [pendingMessages, setPendingMessages] = useState([])
  const pendingMessagesRef = useRef([])

  // Internal helper: synchronously update both the ref and React
  // state. Every public operation funnels through this so the
  // "ref updates before render" contract holds in one place.
  const apply = useCallback((updater) => {
    const next = typeof updater === 'function'
      ? updater(pendingMessagesRef.current)
      : updater
    pendingMessagesRef.current = next
    setPendingMessages(next)
  }, [])

  const add = useCallback((msg) => {
    apply(prev => [
      ...prev,
      { ...msg, position: msg.position ?? prev.length + 1 },
    ])
  }, [apply])

  const swapOptimisticTs = useCallback((cid, serverTs, position) => {
    apply(prev => prev.map(m => {
      if (m.cid !== cid) return m
      const next = { ...m, ts: serverTs ?? m.ts }
      if (position !== undefined) next.position = position
      return next
    }))
  }, [apply])

  const promoteByTs = useCallback((ts) => {
    const current = pendingMessagesRef.current
    const idx = ts != null
      ? current.findIndex(m => m.ts === ts)
      : (current.length > 0 ? 0 : -1)
    if (idx < 0) return null
    const promoted = current[idx]
    const rest = current.filter((_, i) => i !== idx)
    pendingMessagesRef.current = rest
    setPendingMessages(rest)
    return promoted
  }, [])

  const cancelByTs = useCallback((ts) => {
    apply(prev => prev.filter(m => m.ts !== ts))
  }, [apply])

  // Replace the queue wholesale from authoritative server state.
  // Preserves the client-side cid when an existing local entry shares
  // a ts with the server entry — keeps QueuedMessages's expanded
  // state from remounting. Also handles the swap race (R2 in
  // _034-design.md): a hydrate landing concurrently with an
  // optimistic add whose ts the server just claimed should still
  // resolve to the OPTIMISTIC entry's cid (so its React key doesn't
  // flip), not a fresh `s-${ts}` cid.
  const hydrate = useCallback((serverList) => {
    const localByTs = new Map(
      (pendingMessagesRef.current || []).map(m => [m.ts, m.cid])
    )
    const next = (serverList || []).map(m => ({
      ...m,
      cid: localByTs.get(m.ts) || `s-${m.ts}`,
      queued: true,
    }))
    pendingMessagesRef.current = next
    setPendingMessages(next)
  }, [])

  const clear = useCallback(() => {
    pendingMessagesRef.current = []
    setPendingMessages([])
  }, [])

  return {
    pendingMessages,
    pendingMessagesRef,
    add,
    swapOptimisticTs,
    promoteByTs,
    cancelByTs,
    hydrate,
    clear,
  }
}
