import { useState, useRef, useEffect, useLayoutEffect, useCallback } from 'react'
import { apiFetch, getToken } from '../../api/client.js'
import { ProgressiveMarkdown } from './markdown/BlockRenderer.jsx'
import useStreamConnection from './useStreamConnection.js'
import useVoiceInput from './useVoiceInput.js'
import useFileUpload from './useFileUpload.js'
import ConnectionStatus from './ConnectionStatus.jsx'
import ToolBlock from './ToolBlock.jsx'
import MsgContent from './MsgContent.jsx'
import './ChatView.css'


// Module-level map so scroll positions survive component remounts (key={chatId}).
const _scrollPositions = (() => {
  try { return JSON.parse(sessionStorage.getItem('chat-scroll') || '{}') }
  catch { return {} }
})()

export default function ChatView({ chatId, onStreamEnd, onFirstMessage, onSystemEvent, pendingReport, onReportConsumed, builtApp, onOpenApp, onMessageStart }) {
  const [messages, setMessages] = useState([])
  const [totalMessages, setTotalMessages] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [input, setInput] = useState(() => {
    try { return sessionStorage.getItem(`draft:${chatId}`) || '' } catch { return '' }
  })

  const scrollRef = useRef(null)
  const inputRef = useRef(null)
  const spacerRef = useRef(null)
  const fileInputRef = useRef(null)
  const lastUserMsgRef = useRef(null)
  const streamingRef = useRef(null)
  const chatIdStaleRef = useRef(false)
  const hadMessagesRef = useRef(false)
  const promotedRef = useRef(false)
  const needsScrollRef = useRef(false)

  const {
    streamItems,
    latestItemsRef,
    isStreaming,
    connectionError,
    sendMessage: streamSend,
    connectToStream,
    retry,
    disconnect,
  } = useStreamConnection(chatId, {
    onStreamEnd: () => {
      // Promote streamed items directly to the messages array.
      // No server fetch — the server saved incrementally during streaming,
      // and re-fetching causes a visible re-render jitter.
      promoteStreamToMessages()
      setSending(false)
      onStreamEnd?.()
      // Recalculate spacer after the promoted message renders — the effect
      // cleanup resets it to 0, which can allow overscroll if the response
      // is short or empty.
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          recalcSpacer()
        })
      })
    },
    onSystemEvent,
  })

  const { files: pendingFiles, addFiles, removeFile, clearFiles } = useFileUpload({ chatId })

  const { listening, listeningRef, toggleVoice } = useVoiceInput({
    onTranscript: (text) => setInput(text),
    inputRef,
  })

  // Helper to recalculate spacer height based on last user message position.
  // Used after stream end and after stop to prevent overscroll.
  function recalcSpacer() {
    const scrollEl = scrollRef.current
    const userMsgEl = lastUserMsgRef.current
    const spacerEl = spacerRef.current
    if (!scrollEl || !userMsgEl || !spacerEl) return
    const scrollTarget = Math.max(0, userMsgEl.offsetTop - 4)
    const targetH = scrollEl.clientHeight + scrollTarget
    const contentH = scrollEl.scrollHeight - spacerEl.offsetHeight
    const newH = Math.max(0, targetH - contentH)
    spacerEl.style.height = `${newH}px`
  }

  // Converts current streamItems to a message and appends to messages state.
  // Uses a flag to ensure idempotency — handleStop and the SSE onStreamEnd
  // callback can both call this concurrently.  The flag is reset in doSend
  // when a new message starts.
  function promoteStreamToMessages() {
    if (promotedRef.current) return
    const items = latestItemsRef.current
    if (items.length === 0) return
    promotedRef.current = true
    const blocks = items.map(item => {
      if (item.type === 'text') return { type: 'text', content: item.content }
      // Normalize any still-running tools to done — the backend's final save
      // does the same, but the "done" SSE event arrives before that save runs.
      const status = item.status === 'running' ? 'done' : item.status
      return { type: 'tool', ...item, status }
    })
    const content = items
      .filter(i => i.type === 'text')
      .map(i => i.content)
      .join('')
    setMessages(prev => [...prev, { role: 'assistant', content, blocks }])
    setTotalMessages(t => t + 1)
  }

  // Persist draft input so it survives leaving and re-entering the chat.
  useEffect(() => {
    try {
      if (input) sessionStorage.setItem(`draft:${chatId}`, input)
      else sessionStorage.removeItem(`draft:${chatId}`)
    } catch { /* quota exceeded or private browsing */ }
  }, [input, chatId])

  // Auto-size textarea on mount when a draft is restored from session storage.
  useEffect(() => {
    const el = inputRef.current
    if (el && input) {
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 160) + 'px'
    }
  }, [chatId])

  // Fetch messages on mount.
  useEffect(() => {
    let cancelled = false
    chatIdStaleRef.current = false

    apiFetch(`/chats/${chatId}?limit=20`)
      .then(r => r.json())
      .then(data => {
        if (cancelled) return
        let msgs = data.messages || []

        // If the agent is still running, the DB has a partial assistant
        // message saved incrementally during streaming.  The SSE catch-up
        // burst will replay those same events, so drop the partial message
        // to avoid rendering the initial response twice.  Adjust totalMessages
        // to match — promoteStreamToMessages will increment it back when the
        // stream completes.
        const stripped = data.running && msgs.length > 0
          && msgs[msgs.length - 1].role === 'assistant'
        if (stripped) {
          msgs = msgs.slice(0, -1)
        }

        // Fix stale "running" tool blocks in historical messages.
        // If the agent crashed or the CLI exited before emitting tool_end,
        // the DB keeps status:"running" forever. Normalize to "done" for
        // any chat that is no longer active.
        if (!data.running) {
          for (const msg of msgs) {
            if (msg.blocks) {
              for (const blk of msg.blocks) {
                if (blk.type === 'tool' && blk.status === 'running') {
                  blk.status = 'done'
                }
              }
            }
          }
        }

        setMessages(msgs)
        setTotalMessages((data.total || 0) - (stripped ? 1 : 0))
        setOffset(data.offset || 0)
        hadMessagesRef.current = msgs.length > 0
        setLoading(false)

        // Flag for useLayoutEffect to restore scroll after React commits the DOM.
        needsScrollRef.current = true

        // If agent is running, connect to the live SSE stream.
        if (data.running) {
          setSending(true)
          connectToStream(false)
        }
      })
      .catch(() => setLoading(false))

    return () => {
      // Persist scroll positions to sessionStorage so they survive page reloads.
      try { sessionStorage.setItem('chat-scroll', JSON.stringify(_scrollPositions)) } catch {}
      cancelled = true
      chatIdStaleRef.current = true
      loadingOlder.current = false
      disconnect()
    }
  }, [chatId])

  // Restore scroll position after React commits loaded messages to the DOM.
  // useLayoutEffect fires synchronously after DOM mutations, before paint —
  // no flash. The flag ensures this only runs on initial chat load, not
  // on every messages state change (which would cause repeated flashing).
  useLayoutEffect(() => {
    if (!needsScrollRef.current) return
    needsScrollRef.current = false
    const el = scrollRef.current
    if (!el) return
    const saved = _scrollPositions[chatId]
    if (saved != null) {
      el.scrollTop = el.scrollHeight - saved
    } else {
      el.scrollTop = el.scrollHeight
    }
  }, [messages])

  // Load older messages — called from the scroll handler (near top) and the button.
  const loadingOlder = useRef(false)
  function loadOlderMessages() {
    const el = scrollRef.current
    if (!el || loadingOlder.current || loading || offset <= 0) return
    loadingOlder.current = true
    const prevHeight = el.scrollHeight
    apiFetch(`/chats/${chatId}?limit=20&before=${offset}`)
      .then(r => r.json())
      .then(data => {
        if (chatIdStaleRef.current) return
        const older = data.messages || []
        // Older messages are always historical — fix stale running tools.
        for (const msg of older) {
          if (msg.blocks) {
            for (const blk of msg.blocks) {
              if (blk.type === 'tool' && blk.status === 'running') {
                blk.status = 'done'
              }
            }
          }
        }
        setMessages(prev => [...older, ...prev])
        setOffset(data.offset || 0)
        requestAnimationFrame(() => {
          const scrollEl = scrollRef.current
          if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight - prevHeight
          loadingOlder.current = false
        })
      })
      .catch(() => { loadingOlder.current = false })
  }

  function handleScroll() {
    const el = scrollRef.current
    if (!el || loadingOlder.current || loading) return
    // Continuously save scroll as distance-from-bottom.
    // Can't save in useEffect cleanup — DOM is already detached, scrollTop reads 0.
    _scrollPositions[chatId] = el.scrollHeight - el.scrollTop
    if (el.scrollTop < 5 && offset > 0) {
      loadOlderMessages()
    }
  }

  // Dynamic spacer: shrinks as the streaming response grows,
  // keeping the viewport stable (no auto-scroll).
  //
  // The effect re-runs whenever streamItems changes (not just
  // isStreaming) because the streaming <li> doesn't exist until
  // the first stream item arrives.  On the first run streamingRef
  // is null; re-running after items appear lets us attach the
  // MutationObserver to the actual element.
  const hasStreamItems = streamItems.length > 0
  useEffect(() => {
    if (!isStreaming || !spacerRef.current || !scrollRef.current) return

    const scrollEl = scrollRef.current
    const spacerEl = spacerRef.current
    const responseEl = streamingRef.current

    // streaming <li> not yet mounted — wait for next render.
    if (!responseEl) return

    function updateSpacer() {
      const userMsgEl = lastUserMsgRef.current
      if (!userMsgEl) return
      // targetH: the scrollHeight where max scrollTop places the message
      // near the top of the viewport with padding.  doSend scrolls to max,
      // so this formula determines the final message position.
      // No scrollTop anywhere — scrolling never affects this formula.
      // contentH: real content height, excluding the dynamic spacer.
      // 4px breathing room so the message isn't pixel-flush with the toolbar.
      // This value + the 8px chat__list padding-top controls the gap above
      // the sent message. DO NOT increase — keep the message near the top
      // to maximize viewport space for the agent's response below.
      const scrollTarget = Math.max(0, userMsgEl.offsetTop - 4)
      const targetH = scrollEl.clientHeight + scrollTarget
      const contentH = scrollEl.scrollHeight - spacerEl.offsetHeight
      const newH = Math.max(0, targetH - contentH)
      spacerEl.style.height = `${newH}px`
    }

    const observer = new MutationObserver(updateSpacer)
    observer.observe(responseEl, {
      childList: true, subtree: true, characterData: true,
    })

    updateSpacer()
    window.addEventListener('resize', updateSpacer)

    return () => {
      observer.disconnect()
      window.removeEventListener('resize', updateSpacer)
      if (spacerEl) spacerEl.style.height = '0px'
    }
  }, [isStreaming, hasStreamItems])

  function handleFileSelect(e) {
    const fileList = Array.from(e.target.files || [])
    if (!fileList.length) return
    // Reset the input so the same file can be re-selected after removal.
    e.target.value = ''
    addFiles(fileList)
  }

  const doSend = useCallback(async (text) => {
    if (!text.trim() || sending) return
    onMessageStart?.()
    promotedRef.current = false

    // Build attachments from completed pending files.
    const attachments = pendingFiles
      .filter(f => f.status === 'done')
      .map(f => ({ name: f.name, size: f.size, mime_type: f.mime_type }))

    const userMsg = { role: 'user', content: text, ts: Date.now() }
    if (attachments.length > 0) userMsg.attachments = attachments
    setMessages(prev => [...prev, userMsg])
    setTotalMessages(t => t + 1)
    setInput('')
    clearFiles()
    if (inputRef.current) inputRef.current.style.height = 'auto'
    setSending(true)

    // Scroll the user message to the top of the viewport.
    //
    // How it works: set the dynamic spacer to fill the viewport below
    // the message, then scroll to the message's offsetTop.  As the
    // response streams in, the spacer shrinks via MutationObserver.
    //
    // IMPORTANT: .chat__scroll MUST have position:relative for offsetTop
    // to be relative to the scroll container.  Without it, offsetTop is
    // relative to the document body and the scroll position is wrong.
    //
    // IMPORTANT: .spacer-dynamic MUST NOT have a CSS transition.
    // A transition delays the height change, making scrollHeight stale
    // when read immediately after setting the spacer height.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const scrollEl = scrollRef.current
        const userMsgEl = lastUserMsgRef.current
        const spacerEl = spacerRef.current
        if (scrollEl && userMsgEl && spacerEl) {
          const viewH = scrollEl.clientHeight
          // 4px breathing room so the message isn't pixel-flush with the toolbar.
      // This value + the 8px chat__list padding-top controls the gap above
      // the sent message. DO NOT increase — keep the message near the top
      // to maximize viewport space for the agent's response below.
      const scrollTarget = Math.max(0, userMsgEl.offsetTop - 4)
          const belowMsg = scrollEl.scrollHeight - scrollTarget
          spacerEl.style.height = `${Math.max(0, viewH - belowMsg)}px`
          // Scroll to max — accounts for spacer-fixed and any rounding.
          scrollEl.scrollTop = scrollEl.scrollHeight
        }
      })
    })

    try {
      await streamSend(text, attachments.length > 0 ? attachments : undefined)
      // Refresh chat list so this chat appears in the drawer immediately
      // on the first message, rather than waiting for stream end.
      if (!hadMessagesRef.current) {
        hadMessagesRef.current = true
        onFirstMessage?.()
      }
    } catch (err) {
      setSending(false)
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `Error: ${err.message}`, blocks: [] },
      ])
    }
  }, [sending, streamSend, pendingFiles])

  // Auto-submit error reports from mini-apps via the same sendMessage path.
  useEffect(() => {
    if (pendingReport && !sending) {
      const text = pendingReport
      onReportConsumed?.()
      doSend(text)
    }
  }, [pendingReport, sending, onReportConsumed, doSend])

  function handleSubmit(e) {
    e.preventDefault()
    doSend(input.trim())
  }

  async function handleStop() {
    try {
      await fetch('/api/chat/stop', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${getToken()}`,
        },
        body: JSON.stringify({ chat_id: chatId }),
      })
    } catch { /* network error during stop is non-critical */ }
    // promoteStreamToMessages normalizes running tools to done internally,
    // so no need to mutate streamItems beforehand.
    promoteStreamToMessages()
    disconnect()
    setSending(false)
    onStreamEnd?.()

    // Recalculate the spacer after React renders the promoted message.
    // Without this, stopping the agent (especially before it writes anything)
    // collapses the spacer to 0, allowing overscroll past the user's message.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        recalcSpacer()
      })
    })
  }

  const hasMore = offset > 0
  const showEmpty = messages.length === 0 && !isStreaming && !loading && !sending

  return (
    <div className={`chat${showEmpty ? ' chat--empty' : ''}`}>
      {/* Empty state is rendered outside the scroll area so it can be
          vertically centered without fighting scroll/spacer/min-height. */}
      {showEmpty && (
        <div className="chat__empty-wrap">
          <div className="chat__empty">
            <img className="chat__empty-glyph" src="/moebius.png" alt="" width="120" height="120" />
            <p className="chat__empty-title">What's on your mind?</p>
            <p className="chat__empty-sub">Build apps, ask questions, tweak the interface.<br />The agent learns from every session and gets better over time.</p>
          </div>
        </div>
      )}

      {!showEmpty && (
      <div className="chat__scroll" ref={scrollRef} onScroll={handleScroll}>
        {loading && (
          <div className="chat__loading">
            <div className="chat__thinking"><span /><span /><span /></div>
          </div>
        )}

        {/* min-height is disabled during streaming so the dynamic spacer
            math works — min-height adds invisible space at the bottom of
            the list that the spacer doesn't account for, letting the user
            scroll past the content.  Re-enabled when idle for iOS bounce. */}
        <ul className="chat__list" style={sending ? { minHeight: 0 } : undefined}>
          {hasMore && (
            <li className="chat__older">
              <button onClick={loadOlderMessages}>Load earlier messages</button>
            </li>
          )}

          {messages.map((msg, i) => (
            <li
              key={msg.id || msg.ts || `${msg.role}-${i}`}
              className={`chat__msg chat__msg--${msg.role}`}
              ref={msg.role === 'user' && i === messages.length - 1 ? lastUserMsgRef : undefined}
              onClick={msg.ts && msg.role === 'user'
                ? (e) => { e.currentTarget.querySelector('.chat__ts')?.classList.toggle('chat__ts--visible') }
                : undefined}
            >
              <MsgContent msg={msg} chatId={chatId} />
              {msg.ts && msg.role === 'user' && (
                <time className="chat__ts">
                  {new Date(msg.ts).toLocaleString([], {
                    month: 'short', day: 'numeric',
                    hour: '2-digit', minute: '2-digit',
                  })}
                </time>
              )}
            </li>
          ))}

          {/* Streaming response — items rendered in arrival order. */}
          {sending && streamItems.length > 0 && (
            <li className="chat__msg chat__msg--assistant" ref={streamingRef}>
              {streamItems.map((item, i) => {
                if (item.type === 'tool') {
                  return (
                    <div key={`s-${i}`} className="chat__tools">
                      <ToolBlock t={item} />
                    </div>
                  )
                }
                if (item.type === 'text') {
                  const isLast = i === streamItems.length - 1
                  return (
                    <div key={`s-${i}`} className="chat__text chat__text--assistant">
                      <ProgressiveMarkdown text={item.content} />
                      {isLast && <span className="chat__cursor" />}
                    </div>
                  )
                }
                return null
              })}
            </li>
          )}

          {sending && streamItems.length === 0 && !loading && (
            <li className="chat__msg chat__msg--assistant">
              <div className="chat__thinking"><span /><span /><span /></div>
            </li>
          )}
        </ul>

        {/* DO NOT add a CSS transition to .spacer-dynamic — it breaks
            the scroll positioning math (see comment in doSend). */}
        <div className="spacer-dynamic" ref={spacerRef} aria-hidden="true" style={{ height: 0 }} />
      </div>
      )}

      {builtApp && !sending && (
        <div className="chat__open-app">
          <button
            className="chat__open-app-btn"
            onClick={() => onOpenApp?.(builtApp.id)}
          >
            Open {builtApp.name || 'app'} →
          </button>
        </div>
      )}

      <ConnectionStatus error={connectionError} onRetry={retry} />

      <div className="chat__foot">
        <form className="chat__form" onSubmit={handleSubmit}>
          {pendingFiles.length > 0 && (
            <div className="chat__chips">
              {pendingFiles.map(chip => (
                <div
                  key={chip.id}
                  className={`chat__chip${chip.status === 'error' ? ' chat__chip--error' : ''}${chip.objectUrl ? ' chat__chip--image' : ''}`}
                  title={chip.status === 'error' ? chip.error : chip.name}
                >
                  {chip.objectUrl && (
                    <img className="chat__chip-thumb" src={chip.objectUrl} alt="" />
                  )}
                  <span className="chat__chip-name">{chip.name}</span>
                  <span className="chat__chip-status">
                    {chip.status === 'uploading' ? 'uploading…' : chip.status === 'error' ? 'error' : `${Math.round(chip.size / 1024)}KB`}
                  </span>
                  <button
                    type="button"
                    className="chat__chip-remove"
                    onClick={() => removeFile(chip.id)}
                    aria-label={`Remove ${chip.name}`}
                  >×</button>
                </div>
              ))}
            </div>
          )}
          <div className="chat__input-row">
            <input
              type="file"
              multiple
              ref={fileInputRef}
              onChange={handleFileSelect}
              style={{ display: 'none' }}
            />
            <button
              type="button"
              className="chat__attach"
              onClick={() => fileInputRef.current?.click()}
              aria-label="Attach files"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
              </svg>
            </button>
            <textarea
              ref={inputRef}
              className="chat__input"
              value={input}
              onChange={(e) => {
                if (listeningRef.current) return  // block Chrome direct-fill during recording
                setInput(e.target.value)
                e.target.style.height = 'auto'
                e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px'
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(e) }
              }}
              placeholder="Message the agent..."
              disabled={sending}
              rows={1}
            />
            {sending ? (
              <button className="chat__stop" type="button" onClick={handleStop} aria-label="Stop">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
                  <rect width="12" height="12" rx="2" />
                </svg>
              </button>
            ) : (input.trim() && !listening) ? (
              <button
                className="chat__send"
                type="button"
                onClick={handleSubmit}
                aria-label="Send"
                disabled={pendingFiles.some(c => c.status === 'uploading')}
              >
                <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
                  <path d="M6.5 11V2M2 6.5l4.5-4.5 4.5 4.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </button>
            ) : (
              <button
                className={`chat__mic ${listening ? 'chat__mic--active' : ''}`}
                type="button"
                onTouchEnd={(e) => { e.preventDefault(); toggleVoice() }}
                onClick={toggleVoice}
                aria-label={listening ? 'Stop recording' : 'Voice input'}
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <rect x="4.5" y="1" width="5" height="8" rx="2.5" stroke="currentColor" strokeWidth="1.3"/>
                  <path d="M3 7a4 4 0 008 0" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
                  <path d="M7 11v2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
                </svg>
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  )
}
