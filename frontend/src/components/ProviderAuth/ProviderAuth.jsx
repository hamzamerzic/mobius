import { useState, useEffect } from 'react'
import { apiFetch } from '../../api/client.js'
import './ProviderAuth.css'

/**
 * Shared provider auth flow used by SetupWizard and SettingsView.
 *
 * Props:
 *   onDone    — called after successful auth (optional)
 *   compact   — if true, renders inline status row instead of full card
 *   className — additional class on the wrapper (optional)
 */
export default function ProviderAuth({ onDone, compact = false, className = '' }) {
  const [authenticated, setAuthenticated] = useState(false)
  const [loading, setLoading] = useState(true)
  const [authUrl, setAuthUrl] = useState('')
  const [authCode, setAuthCode] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)
  const [justConnected, setJustConnected] = useState(false)

  useEffect(() => {
    apiFetch('/auth/provider/status')
      .then(r => r.json())
      .then(data => setAuthenticated(!!data.authenticated))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  async function startAuth() {
    setError('')
    setAuthUrl('')
    setStarting(true)
    try {
      const res = await apiFetch('/auth/provider/login', { method: 'POST' })
      if (!res.ok) {
        const data = await res.json()
        setError(data.detail || 'Could not start auth.')
        return
      }
      const data = await res.json()
      setAuthUrl(data.auth_url)
      window.open(data.auth_url, '_blank')
    } catch {
      setError('Network error.')
    } finally {
      setStarting(false)
    }
  }

  async function submitCode(e) {
    e.preventDefault()
    if (!authCode.trim()) return
    setError('')
    setSubmitting(true)
    try {
      const res = await apiFetch('/auth/provider/code', {
        method: 'POST',
        body: JSON.stringify({ code: authCode.trim() }),
      })
      if (!res.ok) {
        const data = await res.json()
        setError(data.detail || 'Failed to submit code.')
        return
      }
      const sr = await apiFetch('/auth/provider/status')
      const s = await sr.json()
      if (!s.authenticated) {
        setError('Authentication failed. Try again.')
      } else {
        setAuthenticated(true)
        setAuthUrl('')
        setAuthCode('')
        setJustConnected(true)
        setTimeout(() => setJustConnected(false), 3000)
        onDone?.()
      }
    } catch {
      setError('Network error.')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <p className="pa__muted">Checking…</p>
  }

  // Active auth flow — always show the code input when authUrl is set.
  if (authUrl) {
    return (
      <div className={`pa__flow ${className}`}>
        <p className="pa__muted">
          A sign-in page should have opened.{' '}
          <a href={authUrl} target="_blank" rel="noopener noreferrer">Click here</a>{' '}
          if it didn't. Paste the code below.
        </p>
        <form className="pa__form" onSubmit={submitCode}>
          <input
            className="pa__input"
            value={authCode}
            onChange={(e) => setAuthCode(e.target.value)}
            placeholder="Paste authorization code…"
            autoFocus
            autoComplete="off"
          />
          <button
            className="pa__btn"
            type="submit"
            disabled={submitting || !authCode.trim()}
          >
            {submitting ? 'Connecting…' : 'Connect'}
          </button>
        </form>
        {error && <p className="pa__error">{error}</p>}
      </div>
    )
  }

  // Connected state.
  if (authenticated) {
    if (compact) {
      return (
        <div className={`pa__row ${className}`}>
          <span className="pa__label">
            {justConnected ? <span className="pa__success">Connected</span> : 'Connected'}
          </span>
          <button className="pa__btn pa__btn--sm" onClick={startAuth} disabled={starting}>
            Reconnect
          </button>
        </div>
      )
    }
    return (
      <div className={`pa__done ${className}`}>
        <p className="pa__label">
          {justConnected ? <span className="pa__success">Connected</span> : 'Connected'}
        </p>
        {error && <p className="pa__error">{error}</p>}
      </div>
    )
  }

  // Not connected.
  return (
    <div className={`pa__flow ${className}`}>
      {compact && (
        <p className="pa__muted">Not connected. Sign in to enable the AI agent.</p>
      )}
      <button className="pa__btn" onClick={startAuth} disabled={starting}>
        {starting ? 'Starting…' : 'Sign in with Claude'}
      </button>
      {error && <p className="pa__error">{error}</p>}
    </div>
  )
}
