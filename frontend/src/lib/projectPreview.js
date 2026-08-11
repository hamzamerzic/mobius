const SAFE_PROJECT_PREVIEW_CSP = [
  "default-src 'none'",
  "style-src 'unsafe-inline'",
  "script-src 'unsafe-inline'",
  'img-src data: blob:',
  'font-src data:',
  'media-src data: blob:',
  "form-action 'none'",
  "base-uri 'none'",
].join('; ')

export function safeProjectHtmlDocument(source) {
  const csp = `<meta http-equiv="Content-Security-Policy" content="${SAFE_PROJECT_PREVIEW_CSP}">`
  // Keep the policy ahead of every untrusted byte. Inserting it after a
  // literal <head> is not sufficient: malformed HTML can place a fetching
  // element before that tag, causing the parser to issue a request (and ignore
  // the now-late head) before it ever encounters the policy.
  return `${csp}${String(source ?? '')}`
}

export function projectPreviewSandbox() {
  // Scripts may run so a built web project can be exercised, but the frame is
  // deliberately kept on an opaque origin. CSP blocks network access and the
  // absent sandbox grants block forms, popups, downloads, and parent access.
  return 'allow-scripts'
}

function localProjectPath(reference, entryPath) {
  const raw = String(reference || '').trim()
  if (!raw || raw.startsWith('#') || raw.startsWith('/') || raw.startsWith('//')) return null
  try {
    const base = new URL(entryPath, 'https://project.invalid/')
    const resolved = new URL(raw, base)
    if (resolved.origin !== base.origin) return null
    return decodeURIComponent(resolved.pathname.replace(/^\/+/, ''))
  } catch {
    return null
  }
}

function escapeInlineScript(source) {
  return String(source).replace(/<\/script/gi, '<\\/script')
}

/**
 * Inline a preview's local stylesheets and scripts before placing it in an
 * opaque srcDoc frame. This gives small multi-file projects a faithful,
 * interactive preview without exposing a project directory as a public URL.
 * Missing or remote dependencies stay in the document and are blocked by CSP.
 */
export async function assembleProjectHtmlPreview(source, entryPath, loadText) {
  let document = String(source ?? '')
  const stylesheet = /<link\b([^>]*\brel=["']?stylesheet["']?[^>]*)>/gi
  const script = /<script\b([^>]*\bsrc=["']([^"']+)["'][^>]*)><\/script\s*>/gi

  const styles = [...document.matchAll(stylesheet)]
  for (const match of styles) {
    const href = /\bhref=["']([^"']+)["']/i.exec(match[1])?.[1]
    const path = localProjectPath(href, entryPath)
    if (!path) continue
    try {
      const content = await loadText(path)
      document = document.replace(match[0], `<style data-project-file="${path}">${content}</style>`)
    } catch { /* the CSP-blocked original makes a missing dependency visible */ }
  }

  const scripts = [...document.matchAll(script)]
  for (const match of scripts) {
    const path = localProjectPath(match[2], entryPath)
    if (!path) continue
    try {
      const content = await loadText(path)
      document = document.replace(
        match[0],
        `<script data-project-file="${path}">${escapeInlineScript(content)}</script>`,
      )
    } catch { /* the CSP-blocked original makes a missing dependency visible */ }
  }

  return safeProjectHtmlDocument(document)
}
