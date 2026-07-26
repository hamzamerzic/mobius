import { messageSources, sourceHost, sourceLabel } from './messageSources.js'
import { messageRecall, noteHref, noteLabel } from './memoryRecall.js'

function sourceMark(host) {
  const displayHost = String(host || '').replace(/^www\./i, '')
  return displayHost.match(/[a-z0-9]/i)?.[0]?.toUpperCase() || '•'
}

// A recalled note is not a website, so it gets a mark of its own rather than a
// domain letter. Local and inline for the same reason the web chip's mark is:
// nothing about viewing an answer should contact a remote server.
function MemoryMark() {
  return (
    <svg
      className="chat__source-glyph"
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M8 2.2c-1.5 0-2.6 1-2.8 2.3-1.1.3-1.9 1.2-1.9 2.4 0 .5.2 1 .4 1.4-.3.4-.5.9-.5 1.5 0 1.4 1.2 2.5 2.7 2.5.5 0 1-.1 1.4-.4.2.5.4.9.7 1.2V2.2z"
        fill="currentColor"
        opacity="0.85"
      />
      <path
        d="M8 2.2c1.5 0 2.6 1 2.8 2.3 1.1.3 1.9 1.2 1.9 2.4 0 .5-.2 1-.4 1.4.3.4.5.9.5 1.5 0 1.4-1.2 2.5-2.7 2.5-.5 0-1-.1-1.4-.4-.2.5-.4.9-.7 1.2V2.2z"
        fill="currentColor"
        opacity="0.55"
      />
    </svg>
  )
}

// Everything that informed an answer, surfaced ONCE at the end of the message:
// the notes the agent recalled from Memory, then the web sources it read. See
// memoryRecall.js / messageSources.js for where each comes from and why both
// are derived rather than carried as their own content blocks.
//
// Message level rather than inside the tool row, because a citation is a
// property of the ANSWER, not of the individual search that happened to find
// it: collapsed tool rows hid them, and one search's results are rarely the
// whole citation set.
//
// The recall row exists to make three states distinguishable at a glance —
// remembered these notes / looked and found nothing / never looked (no row).
// The middle state is the one that earns trust, and it is also the prompt to
// write the note that was missing.

export default function MessageSources({ blocks, onInternalNav }) {
  const sources = messageSources(blocks)
  const recall = messageRecall(blocks)
  const notes = recall?.notes || []
  if (sources.length === 0 && !recall) return null

  const handleNoteClick = (event, href) => {
    if (!onInternalNav || !href) return
    // Let the browser own a modified click (new tab, download, middle button)
    // exactly as it does for an ordinary link.
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey
        || event.button !== 0) return
    let url
    try {
      url = new URL(href, window.location.href)
    } catch {
      return
    }
    event.preventDefault()
    onInternalNav(url)
  }

  return (
    <section className="chat__sources" aria-label="What informed this answer">
      <ul className="chat__sources-list">
        {notes.map(note => {
          const label = noteLabel(note)
          const href = noteHref(note)
          const body = (
            <>
              <span className="chat__source-icon" aria-hidden="true">
                <MemoryMark />
              </span>
              <span className="chat__source-copy">
                <span className="chat__source-title">{label}</span>
                <span className="chat__source-host" aria-hidden="true">
                  Memory
                </span>
              </span>
            </>
          )
          return (
            <li key={note.path || note.id} className="chat__source-item">
              {href ? (
                <a
                  className="chat__source-chip chat__source-chip--memory"
                  href={href}
                  title={note.excerpt || label}
                  aria-label={`${label} — recalled from Memory`}
                  onClick={event => handleNoteClick(event, href)}
                >
                  {body}
                </a>
              ) : (
                <span
                  className="chat__source-chip chat__source-chip--memory"
                  title={note.excerpt || label}
                >
                  {body}
                </span>
              )}
            </li>
          )
        })}
        {/* A lookup that came back empty. Deliberately quiet and unclickable:
            it is a fact about the answer, not a destination. */}
        {recall?.empty && (
          <li className="chat__source-item">
            <span className="chat__source-chip chat__source-chip--memory chat__source-chip--quiet">
              <span className="chat__source-icon" aria-hidden="true">
                <MemoryMark />
              </span>
              <span className="chat__source-copy">
                <span className="chat__source-title">
                  Looked back — nothing on this yet
                </span>
              </span>
            </span>
          </li>
        )}
        {sources.map(source => {
          const label = sourceLabel(source)
          const host = sourceHost(source.url)
          const displayHost = host.replace(/^www\./i, '')
          return (
            <li key={source.url} className="chat__source-item">
              <a
                className="chat__source-chip"
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                title={source.snippet || source.title || source.url}
                aria-label={`${label}${host && host !== label ? ` — ${host}` : ''} (opens in a new tab)`}
              >
                {/* A local domain mark is deliberate: remote favicons would
                    contact every cited site merely by viewing an answer. */}
                <span className="chat__source-icon" aria-hidden="true">
                  {sourceMark(host)}
                </span>
                <span className="chat__source-copy">
                  <span className="chat__source-title">{label}</span>
                  {/* A title-less Codex source already reads as its host. */}
                  {host && host !== label && (
                    <span className="chat__source-host" aria-hidden="true">
                      {displayHost}
                    </span>
                  )}
                </span>
              </a>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
