const SAFE_PROJECT_PREVIEW_CSP = [
  "default-src 'none'",
  "style-src 'unsafe-inline'",
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
  // An empty sandbox token list is intentional: no scripts, origin, forms,
  // popups, downloads, or parent navigation are granted to project HTML.
  return ''
}
