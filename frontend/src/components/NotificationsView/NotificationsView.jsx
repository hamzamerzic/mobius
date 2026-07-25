import Bell from 'lucide-react/dist/esm/icons/bell.mjs'
import AppWindow from 'lucide-react/dist/esm/icons/app-window.mjs'
import BotMessageSquare from 'lucide-react/dist/esm/icons/bot-message-square.mjs'
import MessageSquare from 'lucide-react/dist/esm/icons/message-square.mjs'
import Settings2 from 'lucide-react/dist/esm/icons/settings-2.mjs'
import { notificationQueries } from '../../hooks/queries.js'
import { parseNotificationTarget } from '../../lib/notificationTarget.js'
import { formatRelativeTime, iconKindForSource } from './notificationsModel.js'
import './NotificationsView.css'

const ICONS = {
  system: Settings2,
  agent: BotMessageSquare,
  chat: MessageSquare,
  app: AppWindow,
  default: Bell,
}

// The notifications page — a takeover-class view rendered by Shell exactly
// like SettingsView (full-screen takeover in single mode, pane tab in
// builder). TRUST: `title`/`body` are app-token-writable and render as plain
// text only (React escaping); the row `icon` field is deliberately never
// rendered; row clicks go through parseNotificationTarget, which fails closed
// to null → the row simply isn't clickable.
export default function NotificationsView({ active = false, onOpenTarget }) {
  const {
    data, isLoading, isError,
    hasNextPage, isFetchingNextPage, fetchNextPage,
  } = notificationQueries.list.useQuery({ enabled: active })
  const rows = (data?.pages ?? []).flat()

  return (
    <div className="notifications">
      <div className="notifications__content">
        <h1 className="notifications__title">Notifications</h1>
        {isLoading && (
          <p className="notifications__hint" role="status">Loading…</p>
        )}
        {isError && !rows.length && (
          <p className="notifications__hint" role="alert">
            Couldn’t load notifications. They’ll retry automatically.
          </p>
        )}
        {!isLoading && !isError && rows.length === 0 && (
          <div className="notifications__empty">
            <Bell size={28} aria-hidden="true" />
            <p>Nothing yet. Updates from your apps and agents land here.</p>
          </div>
        )}
        <ul className="notifications__list">
          {rows.map((n) => {
            const nav = parseNotificationTarget(n.target)
            const Icon = ICONS[iconKindForSource(n.source_type)] ?? ICONS.default
            const body = (
              <>
                <span className="notifications__row-icon" aria-hidden="true">
                  <Icon size={17} />
                </span>
                <span className="notifications__row-main">
                  <span className="notifications__row-title">{n.title}</span>
                  {n.body ? (
                    <span className="notifications__row-body">{n.body}</span>
                  ) : null}
                </span>
                <time
                  className="notifications__row-time"
                  dateTime={n.sent_at}
                >
                  {formatRelativeTime(n.sent_at)}
                </time>
              </>
            )
            return (
              <li key={n.id} className="notifications__row-item">
                {nav ? (
                  <button
                    type="button"
                    className="notifications__row notifications__row--link"
                    onClick={() => onOpenTarget?.(nav)}
                  >
                    {body}
                  </button>
                ) : (
                  <div className="notifications__row">{body}</div>
                )}
              </li>
            )
          })}
        </ul>
        {hasNextPage && (
          <button
            type="button"
            className="notifications__more"
            disabled={isFetchingNextPage}
            onClick={() => fetchNextPage()}
          >
            {isFetchingNextPage ? 'Loading…' : 'Load older'}
          </button>
        )}
      </div>
    </div>
  )
}
