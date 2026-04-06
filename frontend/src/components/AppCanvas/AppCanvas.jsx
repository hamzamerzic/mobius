import { getToken } from '../../api/client.js'
import './AppCanvas.css'

// version: bumped by Shell when an app_updated event arrives for this
// app.  Appended as ?v= to the iframe src to bust the browser cache
// and force a reload of the frame HTML (which includes theme CSS).
export default function AppCanvas({ appId, version = 0 }) {
  if (!appId) {
    return (
      <div className="canvas canvas--empty">
        <p className="canvas__hint">
          Open the menu to switch apps, or chat to create one.
        </p>
      </div>
    )
  }

  const token = getToken() ?? ''
  const src = `/api/apps/${appId}/frame?token=${encodeURIComponent(token)}&v=${version}`

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
