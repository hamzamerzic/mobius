/* Resolve image-view tool results without handing their base64 payload to the generic text renderer. */

const CHAT_IMAGE_PATH = /^\/data\/chats\/([A-Za-z0-9_-]+)\/(uploads|media)\/([^/]+)$/
const TMP_IMAGE_PATH = /^\/tmp\/(.+)$/
const INLINE_IMAGE_TYPES = new Set([
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'image/bmp',
  'image/avif',
])
const MAX_INLINE_RESULT_CHARS = 32 * 1024 * 1024

/** Claude's Read activity carries a bare path; Codex dynamic tools carry their
 * arguments as a JSON string. Collapse both into the same path contract. */
export function imagePathFromInput(input) {
  if (input && typeof input === 'object') {
    return input.path || input.file_path || ''
  }
  if (typeof input !== 'string') return ''
  const trimmed = input.trim()
  if (!trimmed.startsWith('{')) return trimmed
  try {
    const parsed = JSON.parse(trimmed)
    return parsed?.path || parsed?.file_path || ''
  } catch {
    return trimmed
  }
}

/** Prefer the original chat file: it is smaller than the tool's base64 result
 * and keeps the browser URL behind the existing short-lived media token. */
export function chatImageReference(input) {
  const match = imagePathFromInput(input).match(CHAT_IMAGE_PATH)
  if (!match) return null
  return {
    kind: 'chat',
    chatId: match[1],
    collection: match[2],
    filename: match[3],
  }
}

/** A native Codex image-view event records only its path. Temporary raster
 * images therefore use the owning chat's narrow, token-protected /tmp route
 * instead of waiting for a base64 result that Codex never emits. */
export function temporaryImageReference(input, chatId) {
  if (!chatId) return null
  const match = imagePathFromInput(input).match(TMP_IMAGE_PATH)
  if (!match) return null
  return {
    kind: 'tmp',
    chatId,
    filename: match[1],
  }
}

/** References that can render through an existing protected route without
 * loading the image tool's much larger base64 sidecar. */
export function servedImageReference(input, chatId) {
  return chatImageReference(input) || temporaryImageReference(input, chatId)
}

/** Fallback for image tools that viewed a path outside chat media. This work
 * happens only after the owner expands that activity and the full sidecar has
 * loaded; ordinary transcript rendering never parses the image payload. */
export function inlineImageReference(output) {
  if (
    typeof output !== 'string'
    || output.length === 0
    || output.length > MAX_INLINE_RESULT_CHARS
  ) return null

  try {
    const value = JSON.parse(output)
    const source = value?.type === 'image' ? value.source : null
    if (
      source?.type !== 'base64'
      || typeof source.data !== 'string'
      || !INLINE_IMAGE_TYPES.has(source.media_type)
    ) return null
    return {
      kind: 'inline',
      src: `data:${source.media_type};base64,${source.data}`,
    }
  } catch {
    return null
  }
}

export function toolImageReference(input, output, chatId) {
  return servedImageReference(input, chatId) || inlineImageReference(output)
}
