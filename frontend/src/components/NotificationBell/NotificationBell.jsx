import Bell from 'lucide-react/dist/esm/icons/bell.mjs'
import './NotificationBell.css'

// The header bell — lives in the shell bar's right-side action slot
// (shell__bar-actions), so it renders identically on desktop and mobile by
// construction. Clicking navigates to the notifications page (a takeover-class
// view); the unread badge clears when that page marks everything read
// (seen-on-open model).
export default function NotificationBell({ unreadCount = 0, onClick }) {
  const count = Number.isFinite(unreadCount) && unreadCount > 0 ? unreadCount : 0
  const label = count > 0
    ? `Notifications, ${count} unread`
    : 'Notifications'
  return (
    <button
      type="button"
      className="notification-bell"
      aria-label={label}
      title={label}
      onClick={onClick}
    >
      <Bell size={18} aria-hidden="true" />
      {count > 0 && (
        <span className="notification-bell__badge" aria-hidden="true">
          {count > 99 ? '99+' : count}
        </span>
      )}
    </button>
  )
}
