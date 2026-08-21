/* One-use secure input with a durable prompt-only receipt. */

import { useEffect, useRef, useState } from 'react'
import { api, jsonOrThrow } from '../../api/client.js'
import './SecureInputCard.css'


function settledLabel(status) {
  if (status === 'filled') return 'Provided'
  if (status === 'consuming') return 'Using securely…'
  if (status === 'completed') return 'Provided securely'
  if (status === 'failed') return 'Not used'
  if (status === 'cancelled' || status === 'expired') return 'Not provided'
  return ''
}


export default function SecureInputCard({ block, chatId, interactive = false }) {
  const formRef = useRef(null)
  const [localStatus, setLocalStatus] = useState(block.status || 'pending')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const reveal = block.mode === 'reveal'
  const blockStatus = block.status || 'pending'
  const status = blockStatus === 'pending' ? localStatus : blockStatus
  const open = status === 'pending' && interactive

  useEffect(() => {
    if (block.status && block.status !== 'pending') {
      setLocalStatus(block.status)
    }
  }, [block.status])

  async function submit(event) {
    event.preventDefault()
    if (!open || submitting) return
    const form = formRef.current
    if (!form?.reportValidity()) return

    const data = new FormData(form)
    const fields = {}
    for (const field of block.fields || []) {
      fields[field.name] = String(data.get(field.name) || '')
    }
    if (reveal && data.get('reveal_confirmed') !== 'yes') {
      setError('Confirm that these values may be sent to the AI provider.')
      return
    }

    setError('')
    setSubmitting(true)
    const revealConfirmed = reveal && data.get('reveal_confirmed') === 'yes'
    try {
      await jsonOrThrow(
        await api.secureInputs.submit(chatId, block.request_id, {
          fields,
          reveal_confirmed: revealConfirmed,
        }),
        'Secure input failed',
      )
      // Remove values from the live DOM as soon as Möbius acknowledges its
      // transient server copy. Nothing is mirrored into React state or browser
      // storage; the visible card retains names + status only.
      form.reset()
      setLocalStatus('filled')
    } catch (submitError) {
      setError(submitError?.message || 'Secure input failed. Please try again.')
    } finally {
      // FormData/fields are ordinary JS memory and become unreachable here.
      for (const key of Object.keys(fields)) fields[key] = ''
      setSubmitting(false)
    }
  }

  return (
    <section
      className={`secure-card${reveal ? ' secure-card--reveal' : ''}`}
      aria-label={block.title || 'Secure input'}
    >
      <header className="secure-card__head">
        <span className="secure-card__lock" aria-hidden="true" />
        <div>
          <h3 className="secure-card__title">{block.title || 'Secure input'}</h3>
        </div>
      </header>

      <p className="secure-card__description">
        {block.description || (
          reveal
            ? 'These values will be sent to the AI provider for this turn.'
            : 'These values go directly to a local process and bypass the AI provider.'
        )}
      </p>

      {open ? (
        <form ref={formRef} className="secure-card__form" onSubmit={submit}>
          {(block.fields || []).map(field => (
            <label className="secure-card__field" key={field.name}>
              <span>{field.label}</span>
              <input
                name={field.name}
                type={field.type === 'text' ? 'text' : 'password'}
                autoComplete={field.autocomplete || 'off'}
                required
                disabled={submitting}
                data-chat-inline-editor="secure-input"
              />
            </label>
          ))}

          {reveal && (
            <label className="secure-card__consent">
              <input
                type="checkbox"
                name="reveal_confirmed"
                value="yes"
                disabled={submitting}
              />
              <span>
                I understand these values will be sent to the AI provider.
                Möbius will omit them from its own chat and logs.
              </span>
            </label>
          )}

          {error && <p className="secure-card__error" role="alert">{error}</p>}
          <button className="secure-card__submit" type="submit" disabled={submitting}>
            {submitting
              ? 'Entering…'
              : reveal ? 'Reveal for this turn' : 'Enter securely'}
          </button>
        </form>
      ) : (
        <div className="secure-card__receipts" role="status">
          {(block.fields || []).map(field => (
            <div className="secure-card__receipt" key={field.name}>
              <span className="secure-card__receipt-prompt">
                <span className="secure-card__receipt-lock" aria-hidden="true" />
                <span>{field.label}</span>
              </span>
              <strong>{settledLabel(status) || 'Not provided'}</strong>
            </div>
          ))}
        </div>
      )}

      <p className="secure-card__foot">
        {reveal
          ? (open
              ? 'Explicit reveal sends values to AI; Möbius omits them from its transcript.'
              : 'Receipt saved · revealed values omitted from the Möbius transcript')
          : (open
              ? 'One-time entry · values bypass the chat and AI'
              : 'Receipt saved · entered values omitted')}
      </p>
    </section>
  )
}
