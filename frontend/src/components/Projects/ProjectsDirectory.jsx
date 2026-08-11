import { useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, jsonOrThrow } from '../../api/client.js'
import { projectQueries } from '../../hooks/queries.js'
import './Projects.css'

export default function ProjectsDirectory({ projects, templates, legacy, status, onRetry, onOpen }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [templateId, setTemplateId] = useState('blank')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const requestIdRef = useRef(null)
  const availableTemplates = useMemo(() => (
    templates.length ? templates : [{ key: 'blank', name: 'Blank project', description: '' }]
  ), [templates])

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

  return (
    <section className="projects-directory" aria-label="Projects">
      <header className="projects-directory__header">
        <div>
          <h1>Projects</h1>
          <p>Files and a project-aware chat, kept together in your workspace.</p>
        </div>
      </header>
      <div className="projects-directory__scroll">
        <form className="projects-create" onSubmit={createProject}>
          <div className="projects-create__heading">
            <div>
              <h2>New project</h2>
              <p>Installed apps add project types, skills, and starter files.</p>
            </div>
            <button type="submit" disabled={busy}>{busy ? 'Working…' : 'Create'}</button>
          </div>
          <div className="projects-create__fields">
            <label>
              <span>Name</span>
              <input
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
          </div>
          {availableTemplates.find(template => template.key === templateId)?.description && (
            <p className="projects-create__description">
              {availableTemplates.find(template => template.key === templateId).description}
            </p>
          )}
        </form>

        {error && <p className="projects-error" role="alert">{error}</p>}

        <section className="projects-list" aria-labelledby="projects-list-heading">
          <div className="projects-section-heading">
            <h2 id="projects-list-heading">Your projects</h2>
            <span>{projects.length}</span>
          </div>
          {status === 'loading' ? (
            <p className="projects-empty" role="status">Loading projects…</p>
          ) : status === 'error' ? (
            <div className="projects-empty" role="alert">
              <p>Projects are unavailable.</p>
              <button type="button" onClick={onRetry}>Try again</button>
            </div>
          ) : projects.length === 0 ? (
            <p className="projects-empty">Create a project to keep its files and chats in one place.</p>
          ) : (
            <div className="projects-list__rows">
              {projects.map(project => (
                <button key={project.id} type="button" onClick={() => onOpen(project)}>
                  <span className="projects-list__icon" aria-hidden="true">{project.name.slice(0, 1).toUpperCase()}</span>
                  <span className="projects-list__copy">
                    <strong>{project.name}</strong>
                    <small>{project.template?.name || project.project_type}</small>
                  </span>
                  <span className="projects-list__open" aria-hidden="true">Open</span>
                </button>
              ))}
            </div>
          )}
        </section>

        {legacy.some(row => !row.imported) && (
          <section className="projects-legacy" aria-labelledby="projects-legacy-heading">
            <div className="projects-section-heading">
              <div>
                <h2 id="projects-legacy-heading">Existing app projects</h2>
                <p>Link these without moving or changing their files.</p>
              </div>
            </div>
            <div className="projects-list__rows">
              {legacy.filter(row => !row.imported).map(row => (
                <button
                  key={`${row.app_id}:${row.legacy_project_id}`}
                  type="button"
                  disabled={busy}
                  onClick={() => importLegacy(row)}
                >
                  <span className="projects-list__icon projects-list__icon--legacy" aria-hidden="true">↗</span>
                  <span className="projects-list__copy">
                    <strong>{row.name}</strong>
                    <small>{row.app_name}</small>
                  </span>
                  <span className="projects-list__open">Import</span>
                </button>
              ))}
            </div>
          </section>
        )}
      </div>
    </section>
  )
}
