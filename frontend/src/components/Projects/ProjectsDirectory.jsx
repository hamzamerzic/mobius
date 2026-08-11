import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import Folder from 'lucide-react/dist/esm/icons/folder.mjs'
import Grid2X2 from 'lucide-react/dist/esm/icons/grid-2x2.mjs'
import List from 'lucide-react/dist/esm/icons/list.mjs'
import Plus from 'lucide-react/dist/esm/icons/plus.mjs'
import { api, jsonOrThrow } from '../../api/client.js'
import { projectQueries } from '../../hooks/queries.js'
import './Projects.css'

const VIEW_KEY = 'mobius.projects.directory-view'

function initialView() {
  try {
    return localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'icons'
  } catch {
    return 'icons'
  }
}

export default function ProjectsDirectory({
  projects,
  templates,
  legacy,
  status,
  onRetry,
  onOpen,
  createRequest = 0,
}) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [view, setView] = useState(initialView)
  const [name, setName] = useState('')
  const [templateId, setTemplateId] = useState('blank')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const requestIdRef = useRef(null)
  const nameRef = useRef(null)
  const availableTemplates = useMemo(() => (
    templates.length ? templates : [{ key: 'blank', name: 'Blank project', description: '' }]
  ), [templates])

  useEffect(() => {
    if (creating) nameRef.current?.focus()
  }, [creating])

  useEffect(() => {
    if (!createRequest) return
    setCreating(true)
    setError('')
  }, [createRequest])

  function chooseView(next) {
    setView(next)
    try { localStorage.setItem(VIEW_KEY, next) } catch { /* private browsing */ }
  }

  async function createProject(event) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    requestIdRef.current ||= crypto.randomUUID()
    try {
      const selected = availableTemplates.find(template => template.key === templateId)
      const res = await api.projects.create({
        name: name.trim() || selected?.name || 'Untitled project',
        template_id: templateId,
        recovery_request_id: requestIdRef.current,
      })
      const project = await jsonOrThrow(res, 'Project creation failed:')
      requestIdRef.current = null
      setName('')
      setCreating(false)
      await Promise.all([
        projectQueries.list.invalidate(queryClient),
        projectQueries.legacy.invalidate(queryClient),
      ])
      onOpen(project)
    } catch (cause) {
      setError(cause?.message || 'Could not create the project.')
    } finally {
      setBusy(false)
    }
  }

  async function importLegacy(row) {
    if (busy || row.imported) return
    setBusy(true)
    setError('')
    try {
      const res = await api.projects.importLegacy({
        app_id: row.app_id,
        legacy_project_id: row.legacy_project_id,
        name: row.name,
      })
      const project = await jsonOrThrow(res, 'Project import failed:')
      await Promise.all([
        projectQueries.list.invalidate(queryClient),
        projectQueries.legacy.invalidate(queryClient),
      ])
      onOpen(project)
    } catch (cause) {
      setError(cause?.message || 'Could not import that project.')
    } finally {
      setBusy(false)
    }
  }

  const selectedTemplate = availableTemplates.find(template => template.key === templateId)

  return (
    <section className="projects-directory" aria-label="Projects">
      <header className="projects-directory__header">
        <div>
          <h1>Projects</h1>
          <p>Your files, artifacts, and project chats.</p>
        </div>
        <div className="projects-directory__actions">
          <div className="projects-view-toggle" role="group" aria-label="Project view">
            <button type="button" aria-label="Icon view" aria-pressed={view === 'icons'} onClick={() => chooseView('icons')}><Grid2X2 size={17} /></button>
            <button type="button" aria-label="List view" aria-pressed={view === 'list'} onClick={() => chooseView('list')}><List size={18} /></button>
          </div>
          <button
            type="button"
            className="projects-add"
            aria-label={creating ? 'Close new project form' : 'Create project'}
            aria-expanded={creating}
            onClick={() => { setCreating(current => !current); setError('') }}
          >
            <Plus size={20} />
          </button>
        </div>
      </header>
      <div className="projects-directory__scroll">
        {creating && (
          <form className="projects-create" onSubmit={createProject} onKeyDown={event => {
            if (event.key === 'Escape' && !busy) setCreating(false)
          }}>
            <label>
              <span>Name</span>
              <input
                ref={nameRef}
                value={name}
                placeholder="Untitled project"
                maxLength={256}
                onChange={event => setName(event.target.value)}
              />
            </label>
            <label>
              <span>Type</span>
              <select value={templateId} onChange={event => setTemplateId(event.target.value)}>
                {availableTemplates.map(template => (
                  <option key={template.key} value={template.key}>{template.name}</option>
                ))}
              </select>
            </label>
            <button type="submit" disabled={busy}>{busy ? 'Creating…' : 'Create'}</button>
            {selectedTemplate?.description && <p>{selectedTemplate.description}</p>}
          </form>
        )}

        {error && <p className="projects-error" role="alert">{error}</p>}

        {status === 'loading' ? (
          <p className="projects-empty" role="status">Loading projects…</p>
        ) : status === 'error' ? (
          <div className="projects-empty" role="alert">
            <p>Projects are unavailable.</p>
            <button type="button" onClick={onRetry}>Try again</button>
          </div>
        ) : projects.length === 0 ? (
          <div className="projects-empty">
            <Folder size={42} strokeWidth={1.4} aria-hidden="true" />
            <p>No projects yet.</p>
            <button type="button" onClick={() => setCreating(true)}>Create a project</button>
          </div>
        ) : (
          <div className={`projects-collection projects-collection--${view}`}>
            {projects.map(project => (
              <button key={project.id} type="button" onClick={() => onOpen(project)}>
                <span className="projects-collection__icon" aria-hidden="true"><Folder size={view === 'icons' ? 42 : 24} /></span>
                <span className="projects-collection__copy">
                  <strong>{project.name}</strong>
                  <small>{project.template?.name || project.project_type}</small>
                </span>
              </button>
            ))}
          </div>
        )}

        {legacy.some(row => !row.imported) && (
          <section className="projects-legacy" aria-labelledby="projects-legacy-heading">
            <div className="projects-section-heading">
              <div>
                <h2 id="projects-legacy-heading">Existing app projects</h2>
                <p>Bring these into Projects without moving their files.</p>
              </div>
            </div>
            <div className="projects-collection projects-collection--list">
              {legacy.filter(row => !row.imported).map(row => (
                <button
                  key={`${row.app_id}:${row.legacy_project_id}`}
                  type="button"
                  disabled={busy}
                  onClick={() => importLegacy(row)}
                >
                  <span className="projects-collection__icon" aria-hidden="true"><Folder size={24} /></span>
                  <span className="projects-collection__copy">
                    <strong>{row.name}</strong>
                    <small>{row.app_name}</small>
                  </span>
                  <span className="projects-collection__verb">Import</span>
                </button>
              ))}
            </div>
          </section>
        )}
      </div>
    </section>
  )
}
