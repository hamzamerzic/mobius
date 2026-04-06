import { useEffect, useCallback, useRef } from 'react'
import { LIGHT_COLORS, parseThemeMeta, buildThemeCss } from '../theme.js'
import { apiFetch } from '../api/client.js'

/**
 * Loads and applies the dynamic theme CSS from storage.
 *
 * Extracts @import url(...) lines and injects them as <link> tags so fonts
 * load reliably. Remaining CSS goes into a <style> element. Also handles
 * auto-light-theme on first boot when the user prefers light color scheme.
 */
export default function useTheme() {
  const themeAbortRef = useRef(null)

  const loadTheme = useCallback(() => {
    // Abort any in-flight theme fetch before starting a new one so rapid
    // theme_updated events don't race and apply stale CSS last.
    themeAbortRef.current?.abort()
    themeAbortRef.current = new AbortController()
    const signal = themeAbortRef.current.signal
    apiFetch('/storage/shared/theme.css', { signal })
      .then(r => r.ok ? r.text() : null)
      .then(css => {
        if (signal.aborted) return
        let el = document.getElementById('mobius-theme')
        document.querySelectorAll('link[data-theme-font]').forEach(l => l.remove())

        if (css) {
          const imports = []
          const cssBody = css.replace(
            /@import\s+url\(\s*['"]([^'"]+)['"]\s*\)\s*;[^\S\n]*\n?/g,
            (_, url) => { imports.push(url); return '' }
          )
          imports.forEach(url => {
            const link = document.createElement('link')
            link.rel = 'stylesheet'
            link.href = url
            link.dataset.themeFont = '1'
            document.head.appendChild(link)
          })

          if (!el) {
            el = document.createElement('style')
            el.id = 'mobius-theme'
            document.head.appendChild(el)
          }
          el.textContent = cssBody
          const bgMatch = css.match(/--bg:\s*(#[0-9a-fA-F]{3,8})/)
          if (bgMatch) {
            document.body.style.background = bgMatch[1]
            const meta = document.querySelector('meta[name="theme-color"]')
            if (meta) meta.setAttribute('content', bgMatch[1])
          }
        } else {
          if (el) el.remove()
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => { loadTheme() }, [loadTheme])

  // Auto light theme on first boot.
  useEffect(() => {
    if (!window.matchMedia('(prefers-color-scheme: light)').matches) return
    apiFetch('/storage/shared/theme-mode')
      .then(r => {
        if (r.ok) return
        return apiFetch('/storage/shared/theme.css')
          .then(r => r.ok ? r.text() : '')
          .then(css => {
            const meta = parseThemeMeta(css)
            const newCss = buildThemeCss(LIGHT_COLORS, meta, 'light')
            return Promise.all([
              apiFetch('/storage/shared/theme.css', {
                method: 'PUT',
                body: JSON.stringify({ content: newCss }),
              }),
              apiFetch('/storage/shared/theme-mode', {
                method: 'PUT',
                body: JSON.stringify({ content: JSON.stringify('light') }),
              }),
            ])
          })
          .then(() => loadTheme())
      })
      .catch(() => {})
  }, [])

  return { loadTheme }
}
