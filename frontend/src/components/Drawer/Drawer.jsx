import './Drawer.css'

export default function Drawer({
  open,
  onClose,
  apps,
  activeView,
  activeAppId,
  chats,
  activeChatId,
  onChat,
  onApp,
  onNewChat,
  onDeleteChat,
  onSettings,
}) {
  const allChats = (chats || [])
    .filter(c => c.has_messages)
    .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))

  return (
    <>
      <div
        className={`drawer-overlay ${open ? 'drawer-overlay--visible' : ''}`}
        onClick={onClose}
      />
      <nav className={`drawer ${open ? 'drawer--open' : ''}`} aria-hidden={!open}>
        <div className="drawer__body">

          <button className="drawer__item drawer__item--new" onClick={onNewChat}>
            <span className="drawer__item-text">New chat</span>
          </button>

          <div className="drawer__group drawer__group--flex">
            <p className="drawer__label">History</p>
            <div className="drawer__scroll">
              {allChats.length > 0 ? allChats.map(chat => (
                <button
                  key={chat.id}
                  className={`drawer__item ${activeView === 'chat' && activeChatId === chat.id ? 'drawer__item--active' : ''}`}
                  onClick={() => onChat(chat.id)}
                >
                  <span className="drawer__item-text">{chat.title}</span>
                  <button
                    className="drawer__delete"
                    onClick={(e) => { e.stopPropagation(); onDeleteChat(chat.id) }}
                    aria-label="Delete chat"
                  >
                    <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
                      <path d="M1 1l6 6M7 1L1 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
                    </svg>
                  </button>
                </button>
              )) : (
                <p className="drawer__empty">No conversations yet</p>
              )}
            </div>
          </div>

          {apps.length > 0 && (
            <div className="drawer__group drawer__group--flex">
              <p className="drawer__label">Apps</p>
              <div className="drawer__scroll">
                {apps.map(app => (
                  <button
                    key={app.id}
                    className={`drawer__item ${activeView === 'canvas' && Number(activeAppId) === Number(app.id) ? 'drawer__item--active' : ''}`}
                    onClick={() => onApp(app.id)}
                  >
                    <span className="drawer__item-text">{app.name}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="drawer__group drawer__group--bottom">
            <button
              className={`drawer__item ${activeView === 'settings' ? 'drawer__item--active' : ''}`}
              onClick={onSettings}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
              </svg>
              <span className="drawer__item-text">Settings</span>
            </button>
          </div>

        </div>
      </nav>
    </>
  )
}
