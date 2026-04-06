import { useState, useEffect, useRef } from 'react'
import './NavButton.css'

export default function NavButton({
  apps,
  activeView,
  activeAppId,
  onChat,
  onApp,
  onDeleteApp,
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  function pickChat() {
    onChat()
    setOpen(false)
  }

  function pickApp(id) {
    onApp(id)
    setOpen(false)
  }

  function handleDelete(e, id) {
    e.stopPropagation()
    onDeleteApp(id)
  }

  return (
    <div className="nb" ref={ref}>
      <button
        className={`nb__btn ${open ? 'nb__btn--open' : ''}`}
        onClick={() => setOpen(v => !v)}
        aria-label="Open navigation"
      >
        <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
          <rect x="1" y="3" width="13" height="1.5" rx="0.75" fill="currentColor"/>
          <rect x="1" y="7" width="13" height="1.5" rx="0.75" fill="currentColor"/>
          <rect x="1" y="11" width="13" height="1.5" rx="0.75" fill="currentColor"/>
        </svg>
      </button>

      {open && (
        <div className="nb__popover">
          <button
            className={`nb__item ${activeView === 'chat' ? 'nb__item--active' : ''}`}
            onClick={pickChat}
          >
            <svg className="nb__icon" width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M1.5 2.5a1 1 0 011-1h9a1 1 0 011 1v6a1 1 0 01-1 1H8L5.5 11.5V9.5H2.5a1 1 0 01-1-1v-6z"
                stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/>
            </svg>
            <span className="nb__label">Chat</span>
          </button>

          {apps.length > 0 && (
            <>
              <div className="nb__divider" />
              {apps.map(app => (
                <button
                  key={app.id}
                  className={`nb__item nb__item--app ${activeView === 'canvas' && activeAppId === app.id ? 'nb__item--active' : ''}`}
                  onClick={() => pickApp(app.id)}
                >
                  <svg className="nb__icon" width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <path d="M6 1l1.3 2.6L10.5 4l-2.25 2.2.53 3.1L6 7.8l-2.78 1.5.53-3.1L1.5 4l3.2-.4z"
                      stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round"/>
                  </svg>
                  <span className="nb__label">{app.name}</span>
                  <button
                    className="nb__delete"
                    onClick={(e) => handleDelete(e, app.id)}
                    aria-label={`Delete ${app.name}`}
                  >×</button>
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  )
}
