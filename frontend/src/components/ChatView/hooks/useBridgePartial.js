import { useLayoutEffect, useRef } from 'react'

/**
 * Legacy/mount-time fallback for deciding whether the next persisted-message
 * fetch should replace an in-flight partial kept on mount or append a fresh
 * assistant message.
 *
 * Current streams carry a durable assistant message id; active selection and
 * promotion use that identity first. This hook deliberately retains the old
 * timestamp bridge only for id-less stored data and the narrow first-paint
 * mount handoff. Its caller must reject this fallback when a later visible
 * turn or a different explicit id proves the candidate stale.
 *
 * Why the fallback is ts-based, not role-based: the earlier role-based check
 * ("last message is assistant") regressed when the parallel-agent
 * commit be32e58 started landing errors as the LAST message in a
 * chat — the assistant-role gate would still fire, bridging an
 * error message instead of appending a fresh assistant turn.
 * Timestamp gating is stable inside the legacy path: the kept partial has a
 * specific ts,
 * and any other last-message-ts (including error/system messages
 * persisted after mount) deterministically falls through to APPEND.
 *
 * @param {object} args
 * @param {boolean} args.runningAtMount  data.running from the
 *   initial /chats/{id} fetch — true iff the agent was mid-turn
 *   when the user opened the chat.
 * @param {{ts: number, role: string} | null} args.lastMsgAtMount
 *   The last persisted message at the moment of mount, or null
 *   when the chat had no messages.
 *
 * @returns {{
 *   shouldBridge: (currentLastMsg: {ts?: number} | null | undefined) => boolean,
 *   findBridgeIndex: (messages: Array<{ts?: number, role?: string}> | null | undefined) => number,
 *   markBridged: () => void,
 * }}
 */
export default function useBridgePartial({ runningAtMount, lastMsgAtMount }) {
  // Captured at most ONCE per hook instance, the first time the arguments
  // resolve to a legacy bridge candidate (running=true AND last message is an
  // assistant message with a real ts). After
  // that the captured ts is sticky — subsequent re-renders with
  // different args don't re-arm or clear the gate.
  //
  // The "at-most-once" framing matters because the inputs are
  // populated by an async fetch in ChatView.jsx. The hook may
  // render several times with runningAtMount=false / lastMsg=null
  // before the fetch lands; only the first valid set captures.
  // bridgedRef is the second one-shot — once markBridged() fires,
  // no future render flips back to true.
  const keptPartialTsRef = useRef(null)
  const capturedRef = useRef(false)
  const bridgedRef = useRef(false)

  // Capture the partial-to-bridge AFTER render commits (not in the
  // render body). React's rules forbid render-phase side effects;
  // useLayoutEffect runs synchronously after commit but before
  // paint, so the captured value is ready before any callback
  // (onStreamEnd, promoteStreamToMessages) reads `shouldBridge`.
  // The capturedRef one-shot ensures subsequent renders with the
  // same or new inputs don't re-arm.
  useLayoutEffect(() => {
    if (capturedRef.current) return
    if (!runningAtMount) return
    if (!lastMsgAtMount) return
    if (lastMsgAtMount.role !== 'assistant') return
    if (lastMsgAtMount.ts == null) return
    capturedRef.current = true
    keptPartialTsRef.current = lastMsgAtMount.ts
  }, [runningAtMount, lastMsgAtMount])

  function candidateTs() {
    if (keptPartialTsRef.current != null) return keptPartialTsRef.current
    // Render-time bridge candidate. The layout-effect capture above is still
    // the sticky lifecycle owner, but render needs to suppress the cached DB
    // partial on the FIRST paint after navigating back to a running chat.
    // Waiting for a later render shows the persisted partial and the cached
    // stream snapshot side-by-side. This derivation is pure (no ref writes),
    // so it is safe during render and still lets markBridged() retire it.
    if (!runningAtMount) return null
    if (!lastMsgAtMount) return null
    if (lastMsgAtMount.role !== 'assistant') return null
    return lastMsgAtMount.ts ?? null
  }

  function shouldBridge(currentLastMsg) {
    if (bridgedRef.current) return false
    const ts = candidateTs()
    if (ts == null) return false
    if (!currentLastMsg) return false
    return currentLastMsg.ts === ts
  }

  function findBridgeIndex(messages) {
    if (bridgedRef.current) return -1
    const ts = candidateTs()
    if (ts == null) return -1
    if (!Array.isArray(messages)) return -1
    return messages.findIndex(
      m => m?.role === 'assistant' && m.ts === ts
    )
  }

  function markBridged() {
    bridgedRef.current = true
  }

  return { shouldBridge, findBridgeIndex, markBridged }
}
