import { useQuery } from '@tanstack/react-query'
import { apiFetch, BASE } from '../../api/client.js'
import { appTokenQueryKey } from '../../hooks/queries.js'
import './AppCanvas.css'

// `version` is bumped by Shell when an `app_updated` event arrives
// for this app, busting the iframe cache and forcing a fresh frame
// load (the frame HTML includes the theme CSS, so it needs to refetch
// when the agent updates either the app or the theme).
//
// The app token is cached via the query layer so navigating away
// from the canvas and back doesn't fetch a fresh token, which
// previously cycled the iframe `key` and triggered a full app
// reload (~1–3s of visible jank). Tokens are short-lived but stable
// across React remounts — a 5-minute staleTime is well within the
// server-side validity window.
export default function AppCanvas({ appId, version = 0 }) {
  const { data: token } = useQuery({
    queryKey: appTokenQueryKey(appId),
    enabled: !!appId,
    queryFn: async () => {
      const res = await apiFetch('/auth/app-token', {
        method: 'POST',
        body: JSON.stringify({ app_id: appId }),
      })
      if (!res.ok) throw new Error(`app-token ${res.status}`)
      const data = await res.json()
      return data.token
    },
    staleTime: 5 * 60_000,
  })

  if (!appId) {
    return (
      <div className="canvas canvas--empty">
        <p className="canvas__hint">
          Open the menu to switch apps, or chat to create one.
        </p>
      </div>
    )
  }

  if (!token) return null

  const src = `${BASE}/api/apps/${appId}/frame?token=${encodeURIComponent(token)}&v=${version}`

  // The iframe key intentionally OMITS `token` — the token may
  // refresh (after staleTime) but the iframe should keep its in-app
  // state. Only `appId` and `version` should force a remount.
  return (
    <iframe
      key={`${appId}-${version}`}
      className="canvas"
      src={src}
      title="Mini-app"
      sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-top-navigation-by-user-activation"
      allow="microphone"
    />
  )
}
