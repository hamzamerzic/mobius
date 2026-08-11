import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import ArrowLeft from 'lucide-react/dist/esm/icons/arrow-left.mjs'
import File from 'lucide-react/dist/esm/icons/file.mjs'
import FileCode from 'lucide-react/dist/esm/icons/file-code.mjs'
import FileText from 'lucide-react/dist/esm/icons/file-text.mjs'
import Folder from 'lucide-react/dist/esm/icons/folder.mjs'
import Grid2X2 from 'lucide-react/dist/esm/icons/grid-2x2.mjs'
import Image from 'lucide-react/dist/esm/icons/image.mjs'
import List from 'lucide-react/dist/esm/icons/list.mjs'
import MessageSquare from 'lucide-react/dist/esm/icons/message-square.mjs'
import Plus from 'lucide-react/dist/esm/icons/plus.mjs'
import Upload from 'lucide-react/dist/esm/icons/upload.mjs'
import { api, jsonOrThrow } from '../../api/client.js'
import { projectQueries } from '../../hooks/queries.js'
import { projectPreviewSandbox, safeProjectHtmlDocument } from '../../lib/projectPreview.js'
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

function fileIcon(entry, size) {
  if (entry.type === 'directory') return <Folder size={size} />
  const extension = entry.name.split('.').pop()?.toLowerCase()
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(extension)) return <Image size={size} />
  if (['html', 'css', 'js', 'jsx', 'ts', 'tsx', 'json', 'py'].includes(extension)) return <FileCode size={size} />
  if (['md', 'txt', 'tex', 'csv', 'pdf'].includes(extension)) return <FileText size={size} />
  return <File size={size} />
}

export default function ProjectWorkspace({ project, onOpenChat, onDelete, onRunAction }) {
  const [path, setPath] = useState('')
  const [view, setView] = useState(initialView)
  const [selectedPath, setSelectedPath] = useState(null)
  const [content, setContent] = useState('')
  const [baseline, setBaseline] = useState('')
  const [fileKind, setFileKind] = useState('none')
  const [objectUrl, setObjectUrl] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const uploadRef = useRef(null)

  const filesQuery = useQuery({
    queryKey: projectQueries.keys.files(project.id, path),
    queryFn: async () => jsonOrThrow(
      await api.projects.files(project.id, path),
      'Project files failed:',
    ),
  })
  const entries = filesQuery.data?.entries || []
  const dirty = fileKind === 'text' && content !== baseline

  useEffect(() => {
    setPath('')
    setSelectedPath(null)
    setFileKind('none')
    setContent('')
    setBaseline('')
    setObjectUrl(null)
    setError('')
  }, [project.id])

  useEffect(() => () => {
    if (objectUrl) URL.revokeObjectURL(objectUrl)
  }, [objectUrl])

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
      setFileKind('none')
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
      if (preview.kind === 'html') {
        const data = await jsonOrThrow(res, 'Preview failed:')
        setContent(safeProjectHtmlDocument(data.content))
        setBaseline('')
        setFileKind('html')
      } else {
        if (!res.ok) throw new Error(`Preview failed: ${res.status}`)
        const blob = await res.blob()
        replaceObjectUrl(URL.createObjectURL(blob))
        setContent('')
        setBaseline('')
        setFileKind(preview.kind)
      }
    } catch (cause) {
      setError(cause?.message || 'Could not open that preview.')
      setFileKind('none')
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

  async function createFile() {
    const requested = window.prompt('New file path', path ? `${path}/` : '')
    if (!requested) return
    setBusy(true)
    setError('')
    try {
      await jsonOrThrow(await api.projects.writeFile(project.id, requested, ''), 'File creation failed:')
      await filesQuery.refetch()
      await openFile({ path: requested, name: requested.split('/').pop(), type: 'file' })
    } catch (cause) {
      setError(cause?.message || 'Could not create that file.')
    } finally {
      setBusy(false)
    }
  }

  async function uploadFile(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    const target = [path, file.name].filter(Boolean).join('/')
    setBusy(true)
    setError('')
    try {
      await jsonOrThrow(await api.projects.writeBytes(project.id, target, await file.arrayBuffer()), 'Upload failed:')
      await filesQuery.refetch()
    } catch (cause) {
      setError(cause?.message || 'Could not upload that file.')
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
  const previews = project.template?.previews || []
  const actions = project.template?.actions || []

  if (selectedPath) {
    return (
      <section className="project-workspace project-document" aria-label={`${selectedPath} in ${project.name}`}>
        <header className="project-document__header">
          <button type="button" className="project-icon-button" aria-label="Back to project files" onClick={closeFile}><ArrowLeft size={19} /></button>
          <div><strong>{selectedPath.split('/').pop()}</strong><small>{project.name} / {selectedPath}</small></div>
          <div className="project-document__actions">
            {['binary', 'image', 'pdf'].includes(fileKind) && <button type="button" onClick={downloadFile}>Download</button>}
            {fileKind === 'text' && <button type="button" disabled={!dirty || busy} onClick={saveFile}>{busy ? 'Saving…' : 'Save'}</button>}
          </div>
        </header>
        {error && <p className="projects-error" role="alert">{error}</p>}
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
            <div className="project-preview"><p>Safe preview · scripts, network requests, forms, and parent access are disabled.</p><iframe title={`${selectedPath} preview`} sandbox={projectPreviewSandbox()} srcDoc={content} /></div>
          ) : fileKind === 'image' ? (
            <div className="project-preview project-preview--asset"><img src={objectUrl || ''} alt={`Preview of ${selectedPath}`} /></div>
          ) : fileKind === 'pdf' ? (
            <div className="project-preview project-preview--asset"><iframe title={`${selectedPath} PDF`} src={objectUrl || ''} /></div>
          ) : fileKind === 'binary' ? (
            <div className="project-document__empty"><File size={42} strokeWidth={1.4} /><h2>Preview unavailable</h2><p>This file is preserved as-is and can be downloaded.</p><button type="button" onClick={downloadFile}>Download</button></div>
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
          <div className="projects-view-toggle" role="group" aria-label="File view">
            <button type="button" aria-label="Icon view" aria-pressed={view === 'icons'} onClick={() => chooseView('icons')}><Grid2X2 size={17} /></button>
            <button type="button" aria-label="List view" aria-pressed={view === 'list'} onClick={() => chooseView('list')}><List size={18} /></button>
          </div>
          <button type="button" className="project-icon-button" aria-label="New file" title="New file" disabled={busy} onClick={createFile}><Plus size={19} /></button>
          <button type="button" className="project-icon-button" aria-label="Upload file" title="Upload file" disabled={busy} onClick={() => uploadRef.current?.click()}><Upload size={18} /></button>
          <input ref={uploadRef} type="file" hidden onChange={uploadFile} />
          <button type="button" className="project-workspace__delete" disabled={busy} onClick={deleteProject}>Delete</button>
        </div>
      </header>

      <nav className="project-breadcrumb" aria-label="Project location">
        <button type="button" onClick={() => setPath('')} disabled={!path}>{project.name}</button>
        {breadcrumb.map((part, index) => (
          <button key={`${part}:${index}`} type="button" onClick={() => setPath(breadcrumb.slice(0, index + 1).join('/'))}>/ {part}</button>
        ))}
      </nav>

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
            {!path && (
              <button type="button" className="project-items__chat" onClick={() => onOpenChat(project.chat_id)}>
                <span className="project-items__icon" aria-hidden="true"><MessageSquare size={view === 'icons' ? 38 : 22} /></span>
                <span><strong>Project chat</strong><small>Context for this project</small></span>
              </button>
            )}
            {!path && previews.map(preview => (
              <button key={preview.id} type="button" onClick={() => openPreview(preview)}>
                <span className="project-items__icon" aria-hidden="true"><FileCode size={view === 'icons' ? 38 : 22} /></span>
                <span><strong>{preview.name}</strong><small>Build artifact</small></span>
              </button>
            ))}
            {entries.map(entry => (
              <button key={entry.path} type="button" onClick={() => openFile(entry)}>
                <span className="project-items__icon" aria-hidden="true">{fileIcon(entry, view === 'icons' ? 38 : 22)}</span>
                <span><strong>{entry.name}</strong><small>{entry.type === 'directory' ? 'Folder' : entry.size < 1024 ? `${entry.size} B` : `${Math.ceil(entry.size / 1024)} KB`}</small></span>
              </button>
            ))}
          </div>
        )}
        {!filesQuery.isLoading && !filesQuery.isError && entries.length === 0 && path && <p className="projects-empty">This folder is empty.</p>}
      </div>
      {actions.length > 0 && (
        <footer className="project-actions" role="group" aria-label="Project actions">
          {actions.map(action => <button key={action.id} type="button" onClick={() => onRunAction(project, action)}>{action.name}</button>)}
        </footer>
      )}
    </section>
  )
}
