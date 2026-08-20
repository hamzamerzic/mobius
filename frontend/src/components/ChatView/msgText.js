export function stripAugmentation(text) {
  let cleaned = text.replace(/\s*<agent_experience>[\s\S]*?<\/agent_experience>\s*/g, '\n\n')
  // Preserve a paragraph boundary when removing the hidden attachment manifest.
  // Multiple queued messages are joined with a single newline before steering;
  // if an image-bearing message contributes a trailing "Files in this session"
  // block, deleting the block AND all surrounding whitespace glues the next
  // queued message directly onto the previous one. Replace with one newline,
  // then normalize.
  cleaned = cleaned.replace(/(?:\s*\[Files in this session:\n[\s\S]*?\]\s*)+/g, '\n')
  return cleaned.replace(/\n{3,}/g, '\n\n').trim()
}

// The hidden "Files in this session" manifest the server appends to a queued
// message at compose time and stripAugmentation() hides for display. Editing a
// queued row replaces only its visible text, so the editor re-attaches this
// suffix to keep the row's file references intact — the same content force-steer
// already resends verbatim. Empty when the message carries no such manifest.
export function augmentationSuffix(text) {
  const idx = (text || '').indexOf('\n\n[Files in this session:')
  return idx === -1 ? '' : text.slice(idx)
}
