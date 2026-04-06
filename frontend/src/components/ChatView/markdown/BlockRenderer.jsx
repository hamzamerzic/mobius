import { useMemo } from 'react'
import { Marked } from 'marked'
import markedKatex from 'marked-katex-extension'
import { MemoBlock, BlockToken, MathBlock } from './blocks.jsx'
import '../markdown.css'

/**
 * Configured marked instance with KaTeX math support.
 * The katex extension handles $...$ (inline) and $$...$$ (block)
 * natively in the tokenizer — no placeholder hacks needed.
 *
 * nonStandard:true relaxes spacing requirements around $ delimiters.
 * throwOnError:false prevents KaTeX parse errors from breaking render.
 */
const md = new Marked()
md.use(markedKatex({ nonStandard: true, throwOnError: false }))


function tokenize(text) {
  return md.lexer(text || '')
}


/**
 * ProgressiveMarkdown — streaming mode.
 * Re-lexes on every update; only the last block re-renders
 * thanks to React.memo comparison on token.raw.
 */
export function ProgressiveMarkdown({ text }) {
  const tokens = useMemo(() => tokenize(text), [text])

  return (
    <div
      className="progressive-markdown md-blocks"
      data-is-streaming="true"
      aria-live="polite"
      aria-atomic="false"
    >
      {tokens.map((token, i) => {
        if (token.type === 'blockKatex') {
          return <MathBlock key={i} tex={token.text} />
        }
        if (token.type === 'space') return null
        return <MemoBlock key={i} token={token} />
      })}
    </div>
  )
}


/**
 * StandardMarkdown — history mode.
 * One-shot render, no memoization overhead.
 */
export function StandardMarkdown({ text }) {
  const tokens = useMemo(() => tokenize(text), [text])

  return (
    <div className="standard-markdown md-blocks">
      {tokens.map((token, i) => {
        if (token.type === 'blockKatex') {
          return <MathBlock key={i} tex={token.text} />
        }
        if (token.type === 'space') return null
        return <BlockToken key={i} token={token} />
      })}
    </div>
  )
}
