/**
 * KaTeX rendering helpers.
 * Uses the global window.katex loaded via CDN in index.html.
 */

export function renderBlockMath(tex, element) {
  if (!window.katex) {
    element.textContent = tex
    return
  }
  try {
    window.katex.render(tex, element, {
      displayMode: true,
      throwOnError: false,
    })
  } catch {
    element.textContent = tex
  }
}

export function renderInlineMath(tex, element) {
  if (!window.katex) {
    element.textContent = tex
    return
  }
  try {
    window.katex.render(tex, element, {
      displayMode: false,
      throwOnError: false,
    })
  } catch {
    element.textContent = tex
  }
}
