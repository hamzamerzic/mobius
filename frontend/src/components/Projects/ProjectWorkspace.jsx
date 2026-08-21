import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import Ellipsis from 'lucide-react/dist/esm/icons/ellipsis.mjs'
import MessageSquare from 'lucide-react/dist/esm/icons/message-square.mjs'
import MessageSquarePlus from 'lucide-react/dist/esm/icons/message-square-plus.mjs'
import Pencil from 'lucide-react/dist/esm/icons/pencil.mjs'
import Trash2 from 'lucide-react/dist/esm/icons/trash-2.mjs'
import { api, jsonOrThrow } from '../../api/client.js'
import { projectQueries } from '../../hooks/queries.js'
import ProjectArtifacts from './ProjectArtifacts.jsx'
import ProjectFinder from './ProjectFinder.jsx'
import ProjectTypeIcon from './ProjectTypeIcon.jsx'
import './Projects.css'

// A project workspace has three clearly-separated zones:
//   1. a CHATS strip at the top (its own header — project chats + New chat),
//   2. the Finder (files, in-place inspection), and
//   3. the Artifacts section (buildable website/latex outputs).
// The legacy chats-mixed-into-the-file-grid layout, the icon/list view toggle,
// and the /build/i template-action CTA are gone — artifacts replace the CTA.
export default function ProjectWorkspace({
  project,
  onOpenChat,
  onCreateChat,
  onDelete,
  onOpenArtifact,
  startRenaming = false,
  onRename,
  onRenameEnd,
}) {
  const [activeMenu, setActiveMenu] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState(project.name)
  const [renameBusy, setRenameBusy] = useState(false)
  const [creatingChat, setCreatingChat] = useState(false)
  const moreMenuRef = useRef(null)
  const renameInputRef = useRef(null)
  const queryClient = useQueryClient()

  const chatsQuery = useQuery({
    queryKey: projectQueries.keys.chats(project.id),
    queryFn: async () => {
      const rows = await jsonOrThrow(await api.projects.chats(project.id), 'Project chats failed:')
      return Array.isArray(rows) ? rows : []
    },
    initialData: Array.isArray(project.chats) ? project.chats : undefined,
  })
  const chats = chatsQuery.data || []

  useEffect(() => {
    setActiveMenu(false)
    setError('')
    setRenaming(false)
  }, [project.id])

  useEffect(() => {
    if (!renaming) setRenameValue(project.name)
  }, [project.name, renaming])

  useEffect(() => {
    if (!startRenaming) return
    setRenameValue(project.name)
    setRenaming(true)
    const frame = requestAnimationFrame(() => renameInputRef.current?.select())
    return () => cancelAnimationFrame(frame)
  }, [project.id, project.name, startRenaming])

  useEffect(() => {
    if (!activeMenu) return undefined
    function closeOnPointer(event) {
      if (!moreMenuRef.current?.contains(event.target)) setActiveMenu(false)
    }
    function closeOnEscape(event) {
      if (event.key === 'Escape') setActiveMenu(false)
    }
    document.addEventListener('pointerdown', closeOnPointer)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnPointer)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [activeMenu])

  async function deleteProject() {
    if (busy || !window.confirm(`Delete “${project.name}”, its files, and its chats?`)) return
    setBusy(true)
    setError('')
    const deleted = await onDelete(project)
    if (!deleted) setBusy(false)
  }

  async function saveProjectName() {
    if (renameBusy) return
    const next = renameValue.trim()
    if (!next || next === project.name) {
      setRenameValue(project.name)
      setRenaming(false)
      onRenameEnd?.()
      return
    }
    setRenameBusy(true)
    setError('')
    try {
      await onRename?.(next)
      setRenaming(false)
      onRenameEnd?.()
    } catch (cause) {
      setError(cause?.message || 'Could not rename this project.')
      requestAnimationFrame(() => renameInputRef.current?.focus())
    } finally {
      setRenameBusy(false)
    }
  }

  async function createChat() {
    if (creatingChat) return
    setCreatingChat(true)
    setError('')
    try {
      await onCreateChat?.()
    } catch (cause) {
      setError(cause?.message || 'Could not create a project chat.')
    } finally {
      setCreatingChat(false)
    }
  }

  // Turn a file the owner picked in the finder into a build artifact. The finder
  // already decided the builder from the extension; the id is derived from the
  // path so re-running "build as …" on the same file reuses one artifact rather
  // than piling up duplicates. Then build it and open its tab.
  async function buildFileAsArtifact(path, builder) {
    const base = (path.split('/').pop() || path).replace(/\.[^.]+$/, '') || 'output'
    const id = path.replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_-]+/g, '-')
      .replace(/^-+|-+$/g, '').toLowerCase().slice(0, 64) || 'artifact'
    setError('')
    try {
      try {
        await jsonOrThrow(await api.projects.createArtifact(project.id, {
          id, name: base, builder, source: path,
        }), 'Build failed:')
      } catch (cause) {
        // An artifact for this file already exists — reuse it. Re-raise anything
        // that is not a duplicate (e.g. the source vanished).
        if (!/already|exist|409/i.test(cause?.message || '')) throw cause
      }
      await api.projects.buildArtifact(project.id, id)
      queryClient.invalidateQueries({ queryKey: projectQueries.keys.artifacts(project.id) })
      onOpenArtifact?.(id)
    } catch (cause) {
      setError(cause?.message || 'Could not build that file.')
    }
  }

  return (
    <section className="project-workspace" aria-label={`${project.name} project`}>
      <header className="project-workspace__header">
        <div className="project-workspace__identity">
          <span className="project-workspace__mark" aria-hidden="true"><ProjectTypeIcon value={project} size={23} /></span>
          <div>
            {renaming ? (
              <form className="project-workspace__rename" onSubmit={event => { event.preventDefault(); renameInputRef.current?.blur() }}>
                <input
                  ref={renameInputRef}
                  value={renameValue}
                  maxLength={256}
                  aria-label="Project name"
                  disabled={renameBusy}
                  onChange={event => setRenameValue(event.target.value)}
                  onBlur={() => void saveProjectName()}
                  onKeyDown={event => {
                    if (event.key !== 'Escape' || renameBusy) return
                    event.preventDefault()
                    setRenameValue(project.name)
                    setRenaming(false)
                    onRenameEnd?.()
                  }}
                />
              </form>
            ) : (
              <button type="button" className="project-workspace__title" title="Rename project" onClick={() => { setRenameValue(project.name); setRenaming(true) }}>
                <h1>{project.name}</h1><Pencil size={13} aria-hidden="true" />
              </button>
            )}
            <p>{project.template?.name || project.project_type}</p>
          </div>
        </div>
        <div className="project-workspace__header-actions">
          <div ref={moreMenuRef} className="project-menu">
            <button type="button" className="project-icon-button" aria-label="More project actions" title="More" aria-haspopup="menu" aria-expanded={activeMenu} onClick={() => setActiveMenu(current => !current)}><Ellipsis size={19} /></button>
            {activeMenu && (
              <div className="project-menu__popover project-menu__popover--end" role="menu">
                <button type="button" className="project-menu__danger" role="menuitem" disabled={busy} onClick={() => { setActiveMenu(false); void deleteProject() }}><Trash2 size={16} /> Delete project</button>
              </div>
            )}
          </div>
        </div>
      </header>

      {error && <p className="projects-error" role="alert">{error}</p>}

      <section className="project-chats" aria-labelledby="project-chats-label">
        <div className="project-section-heading">
          <h2 id="project-chats-label"><MessageSquare size={16} aria-hidden="true" /> Chats</h2>
        </div>
        <div className="project-chats__strip">
          {chats.map(chat => (
            <button key={chat.id} type="button" className="project-chats__chat" onClick={() => onOpenChat(chat)}>
              <span className="project-chats__icon" aria-hidden="true"><MessageSquare size={20} /></span>
              <span className="project-chats__copy"><strong>{chat.title || 'New chat'}</strong><small>{chat.has_messages ? 'Chat' : 'Empty chat'}</small></span>
            </button>
          ))}
          <button type="button" className="project-chats__chat project-chats__chat--new" disabled={creatingChat} onClick={() => void createChat()}>
            <span className="project-chats__icon" aria-hidden="true"><MessageSquarePlus size={20} /></span>
            <span className="project-chats__copy"><strong>{creatingChat ? 'Creating…' : 'New chat'}</strong><small>Start a conversation</small></span>
          </button>
        </div>
      </section>

      <ProjectFinder projectId={project.id} projectName={project.name} onBuildFile={buildFileAsArtifact} />

      <ProjectArtifacts projectId={project.id} onOpen={onOpenArtifact} />
    </section>
  )
}
