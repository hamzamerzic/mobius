/*
 * Versioned sessionStorage cache for the currently visible streaming
 * assistant items. The stream transport owns the latest in-memory items and
 * decides when to read, write, or clear them; this module only owns storage.
 * Writes are synchronous, so callers use them at lifecycle boundaries rather
 * than on the frame-paced reveal path.
 */

const STREAM_SNAPSHOT_VERSION = 2
const STREAM_SNAPSHOT_PREFIX = `chat-stream-items:v${STREAM_SNAPSHOT_VERSION}:`

export function streamSnapshotKey(chatId) {
  return `${STREAM_SNAPSHOT_PREFIX}${chatId}`
}

function defaultStorage() {
  try { return globalThis.sessionStorage ?? null } catch { return null }
}

export function readStoredStreamSnapshot(chatId, storage = defaultStorage()) {
  if (!storage || !chatId) return []
  try {
    const raw = storage.getItem(streamSnapshotKey(chatId))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function writeStoredStreamSnapshot(chatId, items, storage = defaultStorage()) {
  if (!storage || !chatId || !Array.isArray(items) || items.length === 0) return
  try {
    storage.setItem(streamSnapshotKey(chatId), JSON.stringify(items))
  } catch {
    // Best-effort only. If sessionStorage is unavailable, the durable DB
    // partial plus SSE catch-up still reconstruct the stream.
  }
}

export function clearStoredStreamSnapshot(chatId, storage = defaultStorage()) {
  if (!storage || !chatId) return
  try {
    storage.removeItem(streamSnapshotKey(chatId))
  } catch {
    // Best-effort cache; ignore storage failures.
  }
}

/**
 * Reclaim every regenerable stream snapshot in one storage area.
 *
 * Composer drafts are owner-authored data; stream snapshots are a remount cache
 * backed by the durable partial plus SSE catch-up. If Web Storage fills up,
 * callers may clear this cache before retrying an owner-data write.
 */
export function reclaimStoredStreamSnapshots(storage = defaultStorage()) {
  if (!storage) return 0

  let reclaimed = 0
  try {
    const keys = []
    for (let index = 0; index < storage.length; index++) {
      const key = storage.key(index)
      if (key?.startsWith(STREAM_SNAPSHOT_PREFIX)) keys.push(key)
    }
    for (const key of keys) {
      storage.removeItem(key)
      reclaimed += 1
    }
  } catch {
    // Best-effort emergency cleanup. The draft store still has its independent
    // memory + IndexedDB path when Web Storage is unavailable.
  }
  return reclaimed
}
