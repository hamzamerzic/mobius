/**
 * Lazy-loads highlight.js and provides a highlight function.
 * Only fetches the library when a code block actually appears.
 */

let hljs = null
let loading = false
const waiters = []

async function loadHljs() {
  if (hljs) return hljs
  if (loading) {
    return new Promise(resolve => waiters.push(resolve))
  }
  loading = true
  try {
    const mod = await import('highlight.js/lib/core')
    hljs = mod.default

    // Register common languages.
    const langs = await Promise.all([
      import('highlight.js/lib/languages/javascript'),
      import('highlight.js/lib/languages/python'),
      import('highlight.js/lib/languages/bash'),
      import('highlight.js/lib/languages/json'),
      import('highlight.js/lib/languages/css'),
      import('highlight.js/lib/languages/xml'),
      import('highlight.js/lib/languages/typescript'),
      import('highlight.js/lib/languages/sql'),
    ])
    const names = [
      'javascript', 'python', 'bash', 'json',
      'css', 'xml', 'typescript', 'sql',
    ]
    langs.forEach((lang, i) => hljs.registerLanguage(names[i], lang.default))

    waiters.forEach(fn => fn(hljs))
    waiters.length = 0
    return hljs
  } catch {
    loading = false
    return null
  }
}

/**
 * Highlights a code string. Returns HTML string or null.
 * Call from a useEffect — triggers lazy load on first use.
 */
export async function highlightCode(code, language) {
  const h = await loadHljs()
  if (!h) return null
  try {
    if (language && h.getLanguage(language)) {
      return h.highlight(code, { language }).value
    }
    return h.highlightAuto(code).value
  } catch {
    return null
  }
}
