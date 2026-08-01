import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import useDialogFocus from '../../hooks/useDialogFocus.js'
import {
  getInstallObservedSnapshot,
  getInstallPromptSnapshot,
  requestInstall,
  subscribeInstallPrompt,
} from '../../lib/installPrompt.js'
import {
  detectInstallPlatform,
  installCopyForPlatform,
} from '../../utils/installPlatform.js'
import {
  initiallyOpenStandaloneInstallCard,
  standaloneInstallCompleted,
} from '../../lib/standaloneBoot.js'

function wasDismissed(slug) {
  try { return sessionStorage.getItem(`mobius:install-dismissed:${slug}`) === '1' }
  catch { return false }
}

function rememberDismissed(slug) {
  try { sessionStorage.setItem(`mobius:install-dismissed:${slug}`, '1') }
  catch { /* session storage is optional */ }
}

export default function StandaloneInstallCard({ app, forceOpen, onClose }) {
  const installState = useSyncExternalStore(
    subscribeInstallPrompt,
    getInstallPromptSnapshot,
    getInstallPromptSnapshot,
  )
  // Only an install this page actually watched happen may be announced. iOS
  // reports standalone display mode inside the in-app browser it opens from a
  // PWA, so the boot-time guess said "installed" to someone who was mid-install.
  const installObserved = useSyncExternalStore(
    subscribeInstallPrompt,
    getInstallObservedSnapshot,
    getInstallObservedSnapshot,
  )
  const platform = detectInstallPlatform()
  const copy = installCopyForPlatform(platform, installObserved, app.name)
  const [open, setOpen] = useState(() => initiallyOpenStandaloneInstallCard({
    installState,
    forceOpen,
    dismissed: wasDismissed(app.slug),
  }))
  // iOS has no install API, so its steps are the whole answer rather than an
  // extra detail — always show them on arrival. They stay correct whether or
  // not the app is already on the home screen (adding twice is harmless),
  // which is exactly why they are safe to show without knowing. Other
  // platforms keep the native prompt primary and reveal steps only if it fails.
  const [showInstructions, setShowInstructions] = useState(
    () => platform.ios || (installState === 'manual' && forceOpen),
  )
  const dialogRef = useRef(null)
  const primaryRef = useRef(null)
  const closeRef = useRef(null)
  const previousInstallStateRef = useRef(installState)

  useEffect(() => {
    if (forceOpen) setOpen(true)
  }, [forceOpen])

  useEffect(() => {
    const previous = previousInstallStateRef.current
    previousInstallStateRef.current = installState
    if (standaloneInstallCompleted(previous, installState)) setOpen(true)
  }, [installState])

  useDialogFocus({
    containerRef: dialogRef,
    initialFocusRef: primaryRef,
    onClose: () => close('dismiss'),
    open,
  })

  function close(reason) {
    if (reason !== 'installed') rememberDismissed(app.slug)
    setOpen(false)
    onClose?.()
  }

  async function install() {
    if (installObserved) {
      close('installed')
      return
    }
    // `showAction` gates this button out once instructions are on screen, so
    // the only reachable case here is revealing them for the first time.
    if (installState !== 'ready') {
      revealInstructions()
      return
    }
    const result = await requestInstall()
    if (result.outcome !== 'accepted') revealInstructions()
  }

  // Revealing instructions unmounts the button that was just activated —
  // `showAction` flips false. Focus would land on <body> while the dialog is
  // open and its siblings are inert, stranding keyboard and screen-reader
  // users outside a trap whose Tab handler matches neither edge. Hand focus to
  // the control that survives.
  function revealInstructions() {
    setShowInstructions(true)
    queueMicrotask(() => closeRef.current?.focus())
  }

  // The action button earns its place only when it can DO something: fire a
  // native install prompt, or reveal guidance not yet on screen. On iPhone
  // neither is ever true — there is no install API and the steps show on
  // arrival — so the card ends at the sentence rather than at a button whose
  // only effect is to close a dialog that already has a close.
  const showAction = installState === 'ready' || !showInstructions

  if (!open) return null

  return (
    <div className="standalone-install__backdrop" onClick={() => close('backdrop')}>
      <section
        ref={dialogRef}
        className="standalone-install"
        role="dialog"
        aria-modal="true"
        aria-labelledby="standalone-install-title"
        onClick={event => event.stopPropagation()}
      >
        <button
          ref={closeRef}
          className="standalone-install__close"
          type="button"
          aria-label="Close"
          onClick={() => close('dismiss')}
        >
          ×
        </button>
        {installObserved ? (
          <>
            <div className="standalone-install__success" aria-hidden="true">✓</div>
            <h1 id="standalone-install-title">{app.name} is on your home screen</h1>
            <button
              ref={primaryRef}
              className="standalone-install__primary"
              type="button"
              onClick={() => close('installed')}
            >
              Got it
            </button>
          </>
        ) : (
          <>
            <div className="standalone-install__identity">
              <img
                className="standalone-install__icon"
                src={`/apps/${encodeURIComponent(app.slug)}/icon-192.png?v=${encodeURIComponent(app.updated_at || '0')}`}
                alt=""
              />
              <h1 id="standalone-install-title">Install {app.name}</h1>
            </div>
            {showInstructions && (platform.ios ? (
              // On iPhone the sentence IS the card, so it gets no box of its
              // own — a bordered panel inside a bordered card is nesting that
              // buys nothing. This document's manifest is the app's, so Add to
              // Home Screen here produces the app, and the arrow points down
              // at the real Share button in Safari's toolbar.
              <p className="standalone-install__steps">
                Tap the <strong>Share</strong> button below, then choose{' '}
                <strong>Add to Home Screen</strong>.
              </p>
            ) : (
              <div className="standalone-install__instructions" role="status">
                <strong>{copy.summary}</strong>
                <span>{copy.body}</span>
              </div>
            ))}
            {platform.ios && showInstructions && (
              <span className="standalone-install__arrow" aria-hidden="true">↓</span>
            )}
            {showAction && (
              <div className="standalone-install__actions">
                <button
                  ref={primaryRef}
                  className="standalone-install__primary"
                  type="button"
                  onClick={install}
                >
                  {installState === 'ready' ? 'Install' : copy.ctaLabel}
                </button>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  )
}
