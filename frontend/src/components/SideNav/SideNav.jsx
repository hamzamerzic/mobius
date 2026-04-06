import './SideNav.css'

export default function SideNav({
  apps,
  activeView,
  activeAppId,
  onChat,
  onApp,
  onDeleteApp,
}) {
  function handleAppContext(e, app) {
    e.preventDefault()
    if (confirm(`Delete "${app.name}"?`)) onDeleteApp(app.id)
  }

  return (
    <nav className="sidenav">
      <button
        className={`sidenav__item ${activeView === 'chat' ? 'sidenav__item--active' : ''}`}
        onClick={onChat}
        data-label="Chat"
        aria-label="Chat"
      >
        <svg width="17" height="17" viewBox="0 0 16 16" fill="none">
          <path d="M2 3a1 1 0 011-1h10a1 1 0 011 1v7a1 1 0 01-1 1H9l-3 2v-2H3a1 1 0 01-1-1V3z"
            stroke="currentColor" strokeWidth="1.25" strokeLinejoin="round"/>
        </svg>
      </button>

      {apps.length > 0 && <div className="sidenav__divider" />}

      {apps.map(app => (
        <button
          key={app.id}
          className={`sidenav__item sidenav__item--app ${activeView === 'canvas' && activeAppId === app.id ? 'sidenav__item--active' : ''}`}
          onClick={() => onApp(app.id)}
          onContextMenu={(e) => handleAppContext(e, app)}
          data-label={app.name}
          aria-label={app.name}
          title=""
        >
          <svg width="13" height="13" viewBox="0 0 12 12" fill="none">
            <path d="M6 1l1.4 2.8L11 4.3l-2.5 2.4.6 3.4L6 8.5l-3.1 1.6.6-3.4L1 4.3l3.6-.5z"
              stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round"/>
          </svg>
        </button>
      ))}
    </nav>
  )
}
