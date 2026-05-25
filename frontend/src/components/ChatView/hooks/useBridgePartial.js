import { useRef } from 'react'

/**
 * Hook that decides whether the next persisted-message fetch should
 * REPLACE the existing last message (bridge an in-flight turn whose
 * partial we kept on mount) or APPEND a fresh assistant message
 * (a brand-new turn since mount).
 *
 * The decision is captured ONCE on mount as a ts (the unique
 * per-message timestamp persisted with every message) and then read
 * by ChatView's promoteStreamToMessages on each promote. After the
 * first promote calls markBridged(), subsequent promotes always
 * append.
 *
 * Why ts-based, not role-based: messages have NO id field
 * (models.py:31 stores the messages array as a JSON column with
 * role/content/ts/blocks; routes/chats_stream.py:157-161 builds
 * messages with just those keys). The earlier role-based check
 * ("last message is assistant") regressed when the parallel-agent
 * commit be32e58 started landing errors as the LAST message in a
 * chat — the assistant-role gate would still fire, bridging an
 * error message instead of appending a fresh assistant turn.
 * ts-based gating is stable: the kept-partial has a specific ts,
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
 *   markBridged: () => void,
 * }}
 */
export default function useBridgePartial({ runningAtMount, lastMsgAtMount }) {
  // Captured ONCE; subsequent argument changes don't re-arm the
  // bridge. The ref-based capture intentionally ignores re-renders
  // so a render with stale args can't flip the gate mid-turn.
  const keptPartialTsRef = useRef(null)
  const capturedRef = useRef(false)
  const bridgedRef = useRef(false)

  if (!capturedRef.current) {
    capturedRef.current = true
    if (runningAtMount
        && lastMsgAtMount
        && lastMsgAtMount.role === 'assistant'
        && lastMsgAtMount.ts != null) {
      keptPartialTsRef.current = lastMsgAtMount.ts
    }
  }

  function shouldBridge(currentLastMsg) {
    if (bridgedRef.current) return false
    if (keptPartialTsRef.current == null) return false
    if (!currentLastMsg) return false
    return currentLastMsg.ts === keptPartialTsRef.current
  }

  function markBridged() {
    bridgedRef.current = true
  }

  return { shouldBridge, markBridged }
}
