// Pure derivation behind the Memory citations on an answer, kept separate so
// the collection/dedupe contract is directly testable.
//
// Sibling of messageSources.js and deliberately the same shape of idea: a
// recalled note is the same KIND of fact as a cited web page — something from
// outside the model's turn that shaped the reply — so it is derived from the
// turn's tool blocks and rendered once, after the answer, rather than carried
// as its own content block (which would fragment a continuous thinking run).
//
// It does NOT reuse the `sources` field. Both `_safe_http_url` (backend) and
// `safeSourceUrl` here hard-require a complete http(s) URL because that value
// goes straight into an `<a href>`; a local note pointer would be silently
// dropped, and relaxing that gate for non-web data would weaken a shared XSS
// path for every citation. A sibling field riding the same tool block keeps it
// intact.
//
// The data itself is stamped by the backend (`memory_recall.py`, applied on the
// one `publish()` funnel), so both runners are covered by construction and the
// live wire, the catch-up log, and the persisted transcript agree.

export const MAX_RECALLED_NOTES = 12
const MAX_RECALL_ROWS_SCANNED = 256

// Only a note id may reach a deep link. The backend already validates the
// path, but this value builds a URL that navigates the shell, so re-check here
// rather than trusting an upstream call site to stay correct forever.
const SAFE_NOTE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/
const SAFE_MEMORY_APP_SLUG = /^memory(?:-[0-9]+)?$/

export function safeNoteId(value) {
  if (typeof value !== 'string') return ''
  const candidate = value.trim()
  if (!candidate || candidate.length > 128) return ''
  return SAFE_NOTE_ID.test(candidate) ? candidate : ''
}

export function safeMemoryAppSlug(value) {
  if (typeof value !== 'string') return ''
  const candidate = value.trim()
  return SAFE_MEMORY_APP_SLUG.test(candidate) ? candidate : ''
}

// Where a pill points: the Memory app, asked to open this note. `?app=<slug>&
// intent=<text>` is the shell's existing internal-nav contract (the same one
// artifact links use), so this adds no new navigation mechanism.
export function noteHref(note) {
  const id = safeNoteId(note?.id)
  if (!id) return ''
  // Old persisted citations predate app_slug and necessarily came from the
  // original unsuffixed install. New citations carry the slug validated from
  // the command path; a present-but-invalid value fails closed.
  const hasAppSlug = typeof note?.app_slug === 'string'
  const appSlug = hasAppSlug ? safeMemoryAppSlug(note.app_slug) : 'memory'
  return appSlug
    ? `/shell/?app=${appSlug}&intent=${encodeURIComponent(`note:${id}`)}`
    : ''
}

// Titles come from the Memory app's own graph. A lookup whose titled section
// lines were carved out of a large tool output still yields a readable label
// from the note id, so a pill is never blank.
export function noteLabel(note) {
  const title = typeof note?.title === 'string' ? note.title.trim() : ''
  if (title) return title
  const id = safeNoteId(note?.id)
  return id ? id.replace(/[-_]+/g, ' ') : ''
}

/**
 * What the turn recalled from Memory, or null when it never looked.
 *
 * Three outcomes, and the difference between them is the whole point:
 *   { notes: [...] }        — it remembered these notes
 *   { notes: [], empty: true }  — it looked and Memory had nothing
 *   null                    — it never looked
 *
 * Without the middle case an owner cannot tell a memory gap from an agent that
 * ignored its memory, which is exactly the distinction that earns trust.
 */
export function messageRecall(blocks) {
  if (!Array.isArray(blocks)) return null
  const notes = []
  const seen = new Set()
  let looked = false
  let empty = false
  let scannedRows = 0

  outer:
  for (const block of blocks) {
    // Compact historical activity carries the same bounded recall metadata on
    // its summary block, so citations remain visible without loading the full
    // tool timeline merely to rediscover them.
    if (!['tool', 'activity'].includes(block?.type)) continue
    const recall = block.recall
    if (!recall || typeof recall !== 'object') continue
    // A lookup still in flight is a live activity beat, not yet a citation.
    if (recall.status === 'searching') continue
    // A failed lookup remains visible in its activity row, but it did not
    // successfully consult the graph and must not mint a source section.
    if (recall.status === 'failed') continue
    looked = true
    if (recall.status === 'empty') empty = true
    if (!Array.isArray(recall.notes)) continue
    for (const note of recall.notes) {
      scannedRows += 1
      if (scannedRows > MAX_RECALL_ROWS_SCANNED) break outer
      const id = safeNoteId(note?.id)
      const key = typeof note?.path === 'string' && note.path ? note.path : id
      if (!id || !key || seen.has(key)) continue
      if (notes.length >= MAX_RECALLED_NOTES) continue
      seen.add(key)
      notes.push(note)
    }
  }

  if (!looked) return null
  // A lookup that returned notes is a hit even if another probe came back
  // empty: the turn did remember something, and the notes say what.
  return { notes, empty: notes.length === 0 && empty }
}
