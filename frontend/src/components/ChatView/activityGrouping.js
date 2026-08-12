import { isDistinctiveActivityTool } from './toolActivityLabel.js'

// Fold adjacent thinking/tool entries into the exact activity stretches shared
// by rendering and cold-transcript preparation. Distinctive tools stand alone;
// prose and other entries preserve their original interleave positions.
// Pure: entry objects are carried through unchanged.
export function groupActivityRuns(entries) {
  const nodes = []
  let run = []

  const flush = () => {
    if (run.length) nodes.push({ group: run })
    run = []
  }

  for (const entry of entries) {
    const type = entry?.item?.type
    // Some providers persist separator text blocks that contain only a line
    // break between reasoning and tool events. They have no visible content,
    // so treating them as prose split one coherent activity into many repeated
    // disclosure rows. Keep meaningful prose as the boundary; ignore only the
    // truly transparent separator.
    const content = entry?.item?.content
    if (type === 'text' && typeof content === 'string' && content.length > 0 && !content.trim()) continue
    if (isDistinctiveActivityTool(entry?.item)) {
      flush()
      nodes.push({ group: [entry] })
    } else if (type === 'tool' || type === 'thinking') {
      run.push(entry)
    } else {
      flush()
      nodes.push({ single: entry })
    }
  }
  flush()
  return nodes
}
