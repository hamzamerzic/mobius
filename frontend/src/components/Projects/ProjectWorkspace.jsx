import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import ArrowLeft from 'lucide-react/dist/esm/icons/arrow-left.mjs'
import File from 'lucide-react/dist/esm/icons/file.mjs'
import FileCode from 'lucide-react/dist/esm/icons/file-code.mjs'
import FileText from 'lucide-react/dist/esm/icons/file-text.mjs'
import Folder from 'lucide-react/dist/esm/icons/folder.mjs'
import FolderPlus from 'lucide-react/dist/esm/icons/folder-plus.mjs'
import Grid2X2 from 'lucide-react/dist/esm/icons/grid-2x2.mjs'
import Image from 'lucide-react/dist/esm/icons/image.mjs'
import List from 'lucide-react/dist/esm/icons/list.mjs'
import MessageSquare from 'lucide-react/dist/esm/icons/message-square.mjs'
import Ellipsis from 'lucide-react/dist/esm/icons/ellipsis.mjs'
import Plus from 'lucide-react/dist/esm/icons/plus.mjs'
import Upload from 'lucide-react/dist/esm/icons/upload.mjs'
import Trash2 from 'lucide-react/dist/esm/icons/trash-2.mjs'
import { api, jsonOrThrow } from '../../api/client.js'
import { projectQueries } from '../../hooks/queries.js'
import { assembleProjectHtmlPreview, projectPreviewSandbox } from '../../lib/projectPreview.js'
import './Projects.css'

const VIEW_KEY = 'mobius.projects.files-view'

function initialView() {
  try { return localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'icons' } catch { return 'icons' }
}

function parentPath(path) {
  const parts = path.split('/').filter(Boolean)
  parts.pop()
  return parts.join('/')
}

function previewButtonLabel(preview) {
  const name = String(preview?.name || '').trim()
  if (!name || name.toLowerCase() === 'preview') return 'Preview'
  if (name.toLowerCase() === 'pdf') return 'Preview PDF'
  return `Preview ${name}`
}

function fileIcon(entry, size) {
  if (entry.type === 'directory') return <Folder size={size} />
  const extension = entry.name.split('.').pop()?.toLowerCase()
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(extension)) return <Image size={size} />
  if (['html', 'css', 'js', 'jsx', 'ts', 'tsx', 'json', 'py'].includes(extension)) return <FileCode size={size} />
  if (['md', 'txt', 'tex', 'csv', 'pdf'].includes(extension)) return <FileText size={size} />
  return <File size={size} />
}

export default function ProjectWorkspace({
  project, onOpenChat, onLocationChange, onDelete, onRunAction,
}) {
  const [path, setPath] = useState('')
  const [view, setView] = useState(initialView)
  const [selectedPath, setSelectedPath] = useState(null)
  const [content, setContent] = useState('')
  const [baseline, setBaseline] = useState('')
  const [fileKind, setFileKind] = useState('none')
  const [objectUrl, setObjectUrl] = useState(null)
  const [creation, setCreation] = useState(null)
  const [creationPath, setCreationPath] = useState('')
  const [activeMenu, setActiveMenu] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const uploadRef = useRef(null)
  const creationInputRef = useRef(null)
  const createMenuRef = useRef(null)
  const moreMenuRef = useRef(null)

  const filesQuery = useQuery({
    queryKey: projectQueries.keys.files(project.id, path),
    queryFn: async () => jsonOrThrow(
      await api.projects.files(project.id, path),
      'Project files failed:',
    ),
  })
  const entries = filesQuery.data?.entries || []
  const dirty = fileKind === 'text' && content !== baseline
  const previews = project.template?.previews || []
  const actions = project.template?.actions || []
  const selectedPreview = previews.find(preview => preview.path === selectedPath)
  const buildAction = actions.find(action => /build/i.test(action.name || action.id || ''))

  useEffect(() => {
    setPath('')
    setSelectedPath(null)
    setFileKind('none')
    setContent('')
    setBaseline('')
    setObjectUrl(null)
    setCreation(null)
    setCreationPath('')
    setActiveMenu(null)
    setError('')
  }, [project.id])

  useEffect(() => () => {
    if (objectUrl) URL.revokeObjectURL(objectUrl)
  }, [objectUrl])

  useEffect(() => {
    onLocationChange?.(selectedPath || path || '')
  }, [onLocationChange, path, selectedPath])

  useEffect(() => {
    if (creation) creationInputRef.current?.focus()
  }, [creation])

  useEffect(() => {
    if (!activeMenu) return undefined
    function closeOnPointer(event) {
      const menu = activeMenu === 'create' ? createMenuRef.current : moreMenuRef.current
      if (!menu?.contains(event.target)) setActiveMenu(null)
    }
    function closeOnEscape(event) {
      if (event.key === 'Escape') setActiveMenu(null)
    }
    document.addEventListener('pointerdown', closeOnPointer)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnPointer)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [activeMenu])

  function chooseView(next) {
    setView(next)
    try { localStorage.setItem(VIEW_KEY, next) } catch { /* private browsing */ }
  }

  function replaceObjectUrl(next) {
    setObjectUrl(current => {
      if (current) URL.revokeObjectURL(current)
      return next
    })
  }

  function closeFile() {
    if (dirty && !window.confirm('Discard your unsaved changes?')) return
    setSelectedPath(null)
    setFileKind('none')
    setContent('')
    setBaseline('')
    replaceObjectUrl(null)
    setError('')
  }

  async function openFile(entry) {
    if (entry.type === 'directory') {
      setPath(entry.path)
      return
    }
    if (dirty && !window.confirm('Discard your unsaved changes?')) return
    setSelectedPath(entry.path)
    setError('')
    setFileKind('loading')
    try {
      const res = await api.projects.readFile(project.id, entry.path)
      const type = res.headers.get('content-type') || ''
      if (type.includes('application/json')) {
        const data = await jsonOrThrow(res, 'File open failed:')
        setContent(data.content)
        setBaseline(data.content)
        setFileKind('text')
      } else if (res.ok) {
        const blob = await res.blob()
        replaceObjectUrl(URL.createObjectURL(blob))
        setFileKind(blob.type.startsWith('image/')
          ? 'image'
          : blob.type === 'application/pdf' || entry.path.toLowerCase().endsWith('.pdf')
            ? 'pdf'
            : 'binary')
        setContent('')
        setBaseline('')
      } else {
        throw new Error(`File open failed: ${res.status}`)
      }
    } catch (cause) {
      setError(cause?.message || 'Could not open that file.')
      setFileKind('error')
    }
  }

  async function openPreview(preview) {
    if (dirty && !window.confirm('Discard your unsaved changes?')) return
    setBusy(true)
    setError('')
    setSelectedPath(preview.path)
    setFileKind('loading')
    try {
      const res = await api.projects.readFile(project.id, preview.path)
      if (!res.ok) {
        if (res.status === 404) {
          setFileKind('missing-preview')
          return
        }
        throw new Error('This preview could not be opened.')
      }
      if (preview.kind === 'html') {
        const data = await jsonOrThrow(res, 'Preview failed:')
        const assembled = await assembleProjectHtmlPreview(
          data.content,
          preview.path,
          async dependencyPath => {
            const dependency = await api.projects.readFile(project.id, dependencyPath)
            const value = await jsonOrThrow(dependency, 'Preview dependency failed:')
            return value.content
          },
        )
        setContent(assembled)
        setBaseline('')
        setFileKind('html')
      } else {
        const blob = await res.blob()
        replaceObjectUrl(URL.createObjectURL(blob))
        setContent('')
        setBaseline('')
        setFileKind(preview.kind)
      }
    } catch (cause) {
      setError(cause?.message || 'Could not open that preview.')
      setFileKind('error')
    } finally {
      setBusy(false)
    }
  }

  async function saveFile() {
    if (!selectedPath || fileKind !== 'text' || busy) return
    setBusy(true)
    setError('')
    try {
      await jsonOrThrow(await api.projects.writeFile(project.id, selectedPath, content), 'File save failed:')
      setBaseline(content)
      await filesQuery.refetch()
    } catch (cause) {
      setError(cause?.message || 'Could not save that file.')
    } finally {
      setBusy(false)
    }
  }

  function beginCreate(kind) {
    setCreation(kind)
    setCreationPath(path ? `${path}/` : '')
    setError('')
  }

  async function submitCreate(event) {
    event.preventDefault()
    const requested = creationPath.trim()
    if (!requested || !creation || busy) return
    setBusy(true)
    setError('')
    try {
      if (creation === 'file') {
        await jsonOrThrow(
          await api.projects.writeFile(project.id, requested, ''),
          'File creation failed:',
        )
      } else {
        await jsonOrThrow(
          await api.projects.createFolder(project.id, requested),
          'Folder creation failed:',
        )
      }
      await filesQuery.refetch()
      const completedKind = creation
      setCreation(null)
      setCreationPath('')
      if (completedKind === 'file') {
        await openFile({ path: requested, name: requested.split('/').pop(), type: 'file' })
      }
    } catch (cause) {
      setError(cause?.message || `Could not create that ${creation}.`)
    } finally {
      setBusy(false)
    }
  }

  async function uploadFile(event) {
    const files = [...(event.target.files || [])]
    event.target.value = ''
    if (files.length === 0) return
    setBusy(true)
    setError('')
    try {
      for (const file of files) {
        const target = [path, file.name].filter(Boolean).join('/')
        await jsonOrThrow(
          await api.projects.writeBytes(project.id, target, await file.arrayBuffer()),
          `Upload of ${file.name} failed:`,
        )
      }
      await filesQuery.refetch()
    } catch (cause) {
      setError(cause?.message || 'Could not upload that file.')
    } finally {
      setBusy(false)
    }
  }

  async function deleteCurrentFile() {
    if (!selectedPath || busy || !window.confirm(`Delete “${selectedPath}”?`)) return
    setBusy(true)
    setError('')
    try {
      await jsonOrThrow(
        await api.projects.deleteFile(project.id, selectedPath),
        'File deletion failed:',
      )
      setSelectedPath(null)
      setFileKind('none')
      setContent('')
      setBaseline('')
      replaceObjectUrl(null)
      await filesQuery.refetch()
    } catch (cause) {
      setError(cause?.message || 'Could not delete that file.')
    } finally {
      setBusy(false)
    }
  }

  async function downloadFile() {
    if (!selectedPath) return
    try {
      const res = await api.projects.readFile(project.id, selectedPath, { download: true })
      if (!res.ok) throw new Error(`Download failed: ${res.status}`)
      const url = URL.createObjectURL(await res.blob())
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = selectedPath.split('/').pop()
      anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 0)
    } catch (cause) {
      setError(cause?.message || 'Could not download that file.')
    }
  }

  async function deleteProject() {
    if (busy || !window.confirm(`Delete “${project.name}” and its project chat?`)) return
    setBusy(true)
    setError('')
    const deleted = await onDelete(project)
    if (!deleted) setBusy(false)
  }

  const breadcrumb = useMemo(() => path.split('/').filter(Boolean), [path])
  if (selectedPath) {
    return (
      <section className="project-workspace project-document" aria-label={`${selectedPath} in ${project.name}`}>
        <header className="project-document__header">
          <button type="button" className="project-icon-button" aria-label="Back to project files" onClick={closeFile}><ArrowLeft size={19} /></button>
          <div><strong>{selectedPath.split('/').pop()}</strong><small>{project.name} / {selectedPath}</small></div>
          <div className="project-document__actions">
            {['binary', 'image', 'pdf'].includes(fileKind) && <button type="button" onClick={downloadFile}>Download</button>}
            {fileKind === 'text' && <button type="button" disabled={!dirty || busy} onClick={saveFile}>{busy ? 'Saving…' : 'Save'}</button>}
            {!['loading', 'missing-preview', 'error'].includes(fileKind) && <button type="button" className="project-document__delete" aria-label={`Delete ${selectedPath}`} title="Delete file" disabled={busy} onClick={deleteCurrentFile}><Trash2 size={17} /></button>}
          </div>
        </header>
        {error && fileKind !== 'error' && <p className="projects-error" role="alert">{error}</p>}
        <div className="project-document__surface">
          {fileKind === 'text' ? (
            <textarea
              aria-label={`Edit ${selectedPath}`}
              value={content}
              spellCheck="false"
              onChange={event => setContent(event.target.value)}
              onKeyDown={event => {
                if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
                  event.preventDefault()
                  void saveFile()
                }
              }}
            />
          ) : fileKind === 'html' ? (
            <div className="project-preview"><p>Isolated preview · local scripts and styles can run; network, forms, downloads, and parent access are blocked.</p><iframe title={`${selectedPath} preview`} sandbox={projectPreviewSandbox()} srcDoc={content} /></div>
          ) : fileKind === 'image' ? (
            <div className="project-preview project-preview--asset"><img src={objectUrl || ''} alt={`Preview of ${selectedPath}`} /></div>
          ) : fileKind === 'pdf' ? (
            <div className="project-preview project-preview--asset"><iframe title={`${selectedPath} PDF`} src={objectUrl || ''} /></div>
          ) : fileKind === 'binary' ? (
            <div className="project-document__empty"><File size={42} strokeWidth={1.4} /><h2>Preview unavailable</h2><p>This file is preserved as-is and can be downloaded.</p><button type="button" onClick={downloadFile}>Download</button></div>
          ) : fileKind === 'missing-preview' ? (
            <div className="project-document__empty" role="status">
              <FileText size={42} strokeWidth={1.4} />
              <h2>{selectedPreview?.name || 'Preview'} isn’t ready</h2>
              <p>{buildAction ? 'Build this project first. The preview will be ready when the agent finishes.' : `Create ${selectedPath} in this project, then try again.`}</p>
              {buildAction && <button type="button" onClick={() => onRunAction(project, buildAction)}>{buildAction.name}</button>}
              {!buildAction && selectedPreview && <button type="button" onClick={() => openPreview(selectedPreview)}>Try again</button>}
            </div>
          ) : fileKind === 'error' ? (
            <div className="project-document__empty" role="alert">
              <File size={42} strokeWidth={1.4} />
              <h2>Couldn’t open this file</h2>
              <p>{error || 'The file may have moved or become unavailable.'}</p>
              {selectedPreview && <button type="button" onClick={() => openPreview(selectedPreview)}>Try again</button>}
            </div>
          ) : (
            <div className="project-document__empty" role="status"><p>Opening file…</p></div>
          )}
        </div>
      </section>
    )
  }

  return (
    <section className="project-workspace" aria-label={`${project.name} project`}>
      <header className="project-workspace__header">
        <div className="project-workspace__identity">
          <span className="project-workspace__mark" aria-hidden="true"><Folder size={25} /></span>
          <div><h1>{project.name}</h1><p>{project.template?.name || project.project_type}</p></div>
        </div>
        <div className="project-workspace__header-actions">
          <button type="button" className="project-icon-button" aria-label="Open project chat" title="Project chat" onClick={() => onOpenChat(project.chat_id)}><MessageSquare size={18} /></button>
          <div className="projects-view-toggle" role="group" aria-label="File view">
            <button type="button" aria-label="Icon view" aria-pressed={view === 'icons'} onClick={() => chooseView('icons')}><Grid2X2 size={17} /></button>
            <button type="button" aria-label="List view" aria-pressed={view === 'list'} onClick={() => chooseView('list')}><List size={18} /></button>
          </div>
          <div ref={createMenuRef} className="project-menu">
            <button type="button" className="project-icon-button" aria-label="Add to project" title="Add to project" aria-haspopup="menu" aria-expanded={activeMenu === 'create'} onClick={() => setActiveMenu(current => current === 'create' ? null : 'create')}><Plus size={19} /></button>
            {activeMenu === 'create' && (
              <div className="project-menu__popover" role="menu">
                <button type="button" role="menuitem" disabled={busy} onClick={() => { setActiveMenu(null); beginCreate('file') }}><FileText size={16} /> New file</button>
                <button type="button" role="menuitem" disabled={busy} onClick={() => { setActiveMenu(null); beginCreate('folder') }}><FolderPlus size={16} /> New folder</button>
                <button type="button" role="menuitem" disabled={busy} onClick={() => { setActiveMenu(null); uploadRef.current?.click() }}><Upload size={16} /> Upload files</button>
              </div>
            )}
          </div>
          <input ref={uploadRef} type="file" multiple hidden onChange={uploadFile} />
          <div ref={moreMenuRef} className="project-menu">
            <button type="button" className="project-icon-button" aria-label="More project actions" title="More" aria-haspopup="menu" aria-expanded={activeMenu === 'more'} onClick={() => setActiveMenu(current => current === 'more' ? null : 'more')}><Ellipsis size={19} /></button>
            {activeMenu === 'more' && (
              <div className="project-menu__popover project-menu__popover--end" role="menu">
                <button type="button" className="project-menu__danger" role="menuitem" disabled={busy} onClick={() => { setActiveMenu(null); void deleteProject() }}><Trash2 size={16} /> Delete project</button>
              </div>
            )}
          </div>
        </div>
      </header>

      <nav className="project-breadcrumb" aria-label="Project location">
        <button type="button" onClick={() => setPath('')} disabled={!path}>{project.name}</button>
        {breadcrumb.map((part, index) => (
          <button key={`${part}:${index}`} type="button" onClick={() => setPath(breadcrumb.slice(0, index + 1).join('/'))}>/ {part}</button>
        ))}
      </nav>

      {creation && (
        <form className="project-inline-create" onSubmit={submitCreate} onKeyDown={event => {
          if (event.key === 'Escape' && !busy) setCreation(null)
        }}>
          <label htmlFor={`project-create-${project.id}`}>
            {creation === 'file' ? 'New file' : 'New folder'}
          </label>
          <input
            id={`project-create-${project.id}`}
            ref={creationInputRef}
            value={creationPath}
            maxLength={2048}
            placeholder={path ? `${path}/name` : 'name'}
            onChange={event => setCreationPath(event.target.value)}
          />
          <button type="submit" disabled={busy || !creationPath.trim()}>{busy ? 'Creating…' : 'Create'}</button>
          <button type="button" disabled={busy} onClick={() => setCreation(null)}>Cancel</button>
        </form>
      )}

      {error && <p className="projects-error" role="alert">{error}</p>}
      <div className="project-browser">
        {path && (
          <button type="button" className="project-browser__back" onClick={() => setPath(parentPath(path))}><ArrowLeft size={17} /> Parent folder</button>
        )}
        {filesQuery.isLoading ? (
          <p className="projects-empty" role="status">Loading files…</p>
        ) : filesQuery.isError ? (
          <div className="projects-empty" role="alert"><p>Files are unavailable.</p><button type="button" onClick={() => filesQuery.refetch()}>Try again</button></div>
        ) : (
          <div className={`project-items project-items--${view}`}>
            {entries.map(entry => (
              <button key={entry.path} type="button" onClick={() => openFile(entry)}>
                <span className="project-items__icon" aria-hidden="true">{fileIcon(entry, view === 'icons' ? 38 : 22)}</span>
                <span><strong>{entry.name}</strong><small>{entry.type === 'directory' ? 'Folder' : entry.size < 1024 ? `${entry.size} B` : `${Math.ceil(entry.size / 1024)} KB`}</small></span>
              </button>
            ))}
          </div>
        )}
        {!filesQuery.isLoading && !filesQuery.isError && entries.length === 0 && !path && (
          <div className="projects-empty">
            <Folder size={42} strokeWidth={1.4} aria-hidden="true" />
            <p>This project is empty.</p>
            <button type="button" onClick={() => beginCreate('file')}>Add the first file</button>
          </div>
        )}
        {!filesQuery.isLoading && !filesQuery.isError && entries.length === 0 && path && <p className="projects-empty">This folder is empty.</p>}
      </div>
      {(previews.length > 0 || actions.length > 0) && (
        <footer className="project-actions" role="group" aria-label="Project actions">
          {previews.map(preview => (
            <button key={preview.id} type="button" disabled={busy} onClick={() => openPreview(preview)}>
              {previewButtonLabel(preview)}
            </button>
          ))}
          {actions.map(action => <button key={action.id} type="button" onClick={() => onRunAction(project, action)}>{action.name}</button>)}
        </footer>
      )}
    </section>
  )
}
