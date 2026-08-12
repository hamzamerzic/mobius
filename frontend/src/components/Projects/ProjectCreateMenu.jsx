import { useEffect, useMemo, useRef, useState } from 'react'
import Plus from 'lucide-react/dist/esm/icons/plus.mjs'
import ProjectTypeIcon from './ProjectTypeIcon.jsx'
import './ProjectCreateMenu.css'

const FALLBACK_TEMPLATES = [{
  key: 'blank',
  name: 'Blank project',
  description: 'Start with an empty folder.',
}]

export default function ProjectCreateMenu({
  templates,
  onCreate,
  className = '',
  align = 'end',
  label = 'Create project',
}) {
  const [open, setOpen] = useState(false)
  const [busyKey, setBusyKey] = useState(null)
  const [error, setError] = useState('')
  const rootRef = useRef(null)
  const firstItemRef = useRef(null)
  const availableTemplates = useMemo(
    () => templates?.length ? templates : FALLBACK_TEMPLATES,
    [templates],
  )

  useEffect(() => {
    if (!open) return undefined
    const focusFrame = requestAnimationFrame(() => firstItemRef.current?.focus())
    function dismiss(event) {
      if (!rootRef.current?.contains(event.target)) setOpen(false)
    }
    function closeOnEscape(event) {
      if (event.key !== 'Escape') return
      setOpen(false)
      rootRef.current?.querySelector('[data-project-create-trigger]')?.focus()
    }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      cancelAnimationFrame(focusFrame)
      document.removeEventListener('pointerdown', dismiss)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  async function choose(template) {
    if (busyKey) return
    setBusyKey(template.key)
    setError('')
    try {
      await onCreate?.(template)
      setOpen(false)
    } catch (cause) {
      setError(cause?.message || 'Could not create that project.')
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <div ref={rootRef} className={`project-create-menu ${className}`.trim()}>
      <button
        type="button"
        className="project-create-menu__trigger"
        data-project-create-trigger=""
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => { setOpen(current => !current); setError('') }}
      >
        <Plus size={21} strokeWidth={2} />
      </button>
      {open && (
        <div className={`project-create-menu__popover project-create-menu__popover--${align}`} role="menu" aria-label="Project types">
          <div className="project-create-menu__heading">New project</div>
          {availableTemplates.map((template, index) => (
            <button
              key={template.key}
              ref={index === 0 ? firstItemRef : null}
              type="button"
              role="menuitem"
              disabled={busyKey != null}
              onClick={() => void choose(template)}
            >
              <span className="project-create-menu__icon" aria-hidden="true">
                <ProjectTypeIcon value={template} size={19} />
              </span>
              <span>
                <strong>{busyKey === template.key ? 'Creating…' : template.name}</strong>
                {template.description && <small>{template.description}</small>}
              </span>
            </button>
          ))}
          {error && <p role="alert">{error}</p>}
        </div>
      )}
    </div>
  )
}
