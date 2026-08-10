/* A quiet timeline marker for provider-native context compaction. */

import './ContextCompactionMarker.css'

const PROVIDER_LABELS = {
  claude: 'Claude',
  codex: 'Codex',
}

function compactionMeta(block) {
  const provider = PROVIDER_LABELS[block?.provider] || null
  const trigger = block?.trigger === 'manual' ? 'manual' : null
  return [provider, trigger].filter(Boolean).join(' · ')
}

export default function ContextCompactionMarker({ block }) {
  const meta = compactionMeta(block)
  const ariaLabel = meta
    ? `Context compacted — ${meta}`
    : 'Context compacted'

  // Intentionally not MarkerCard: native provider compaction exposes no
  // readable briefing and asks for no interaction. A borderless rule keeps it
  // chronological and visible without borrowing the accent card reserved for
  // deliberate conversation summaries and provider handoffs.
  return (
    <div className="chat__context-compaction" role="note" aria-label={ariaLabel}>
      <span className="chat__context-compaction-label">Context compacted</span>
      {meta && <span className="chat__context-compaction-meta">{meta}</span>}
    </div>
  )
}
