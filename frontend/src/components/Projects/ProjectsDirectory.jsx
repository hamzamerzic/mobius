import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import Grid2X2 from 'lucide-react/dist/esm/icons/grid-2x2.mjs'
import List from 'lucide-react/dist/esm/icons/list.mjs'
import { api, jsonOrThrow } from '../../api/client.js'
import { projectQueries } from '../../hooks/queries.js'
import ProjectCreateMenu from './ProjectCreateMenu.jsx'
import ProjectTypeIcon from './ProjectTypeIcon.jsx'
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
  onCreate,
}) {
  const queryClient = useQueryClient()
  const [view, setView] = useState(initialView)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  function chooseView(next) {
    setView(next)
    try { localStorage.setItem(VIEW_KEY, next) } catch { /* private browsing */ }
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
          <ProjectCreateMenu templates={templates} onCreate={onCreate} className="projects-add-menu" />
        </div>
      </header>
      <div className="projects-directory__scroll">
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
            <ProjectTypeIcon value="blank" size={42} strokeWidth={1.4} aria-hidden="true" />
            <p>No projects yet.</p>
            <button type="button" onClick={() => onCreate?.(templates[0] || { key: 'blank', name: 'Blank project' })}>Create a project</button>
          </div>
        ) : (
          <div className={`projects-collection projects-collection--${view}`}>
            {projects.map(project => (
              <button key={project.id} type="button" onClick={() => onOpen(project)}>
                <span className="projects-collection__icon" aria-hidden="true"><ProjectTypeIcon value={project} size={view === 'icons' ? 38 : 22} /></span>
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
                  <span className="projects-collection__icon" aria-hidden="true"><ProjectTypeIcon value={row.app_name} size={22} /></span>
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
