import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, jsonOrThrow } from '../../api/client.js'
import { projectQueries } from '../../hooks/queries.js'
import { projectPreviewSandbox, safeProjectHtmlDocument } from '../../lib/projectPreview.js'
import './Projects.css'

function parentPath(path) {
  const parts = path.split('/').filter(Boolean)
  parts.pop()
  return parts.join('/')
}

function fileLabel(path) {
  return path.split('/').pop() || path
}

export default function ProjectWorkspace({ project, onOpenChat, onDelete, onRunAction }) {
  const [path, setPath] = useState('')
  const [selectedPath, setSelectedPath] = useState(null)
  const [content, setContent] = useState('')
  const [baseline, setBaseline] = useState('')
  const [fileKind, setFileKind] = useState('none')
  const [openItems, setOpenItems] = useState([])
  const [activeItemKey, setActiveItemKey] = useState(null)
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
    setOpenItems([])
    setActiveItemKey(null)
    setObjectUrl(null)
    setError('')
  }, [project.id])

  useEffect(() => () => {
    if (objectUrl) URL.revokeObjectURL(objectUrl)
  }, [objectUrl])

  function replaceObjectUrl(next) {
    setObjectUrl(current => {
      if (current) URL.revokeObjectURL(current)
      return next
    })
  }

  function rememberItem(item) {
    setOpenItems(current => current.some(row => row.key === item.key)
      ? current
      : [...current, item])
    setActiveItemKey(item.key)
  }

  async function openFile(entry) {
    if (dirty && !window.confirm('Discard your unsaved changes?')) return
    setSelectedPath(entry.path)
    setError('')
    if (entry.type === 'directory') {
      setPath(entry.path)
      setSelectedPath(null)
      setActiveItemKey(null)
      setFileKind('none')
      return
    }
    rememberItem({ key: `file:${entry.path}`, path: entry.path, name: fileLabel(entry.path), type: 'file' })
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
    rememberItem({
      key: `preview:${preview.id}`,
      path: preview.path,
      name: preview.name,
      type: 'preview',
      preview,
    })
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

  function activateItem(item) {
    if (item.type === 'preview') void openPreview(item.preview)
    else void openFile({ path: item.path, type: 'file' })
  }

  function closeItem(event, item) {
    event.stopPropagation()
    if (item.key === activeItemKey && dirty && !window.confirm('Discard your unsaved changes?')) return
    const next = openItems.filter(row => row.key !== item.key)
    setOpenItems(next)
    if (item.key !== activeItemKey) return
    const fallback = next.at(-1)
    if (fallback) activateItem(fallback)
    else {
      setActiveItemKey(null)
      setSelectedPath(null)
      setFileKind('none')
      setContent('')
      setBaseline('')
      replaceObjectUrl(null)
    }
  }

  async function saveFile() {
    if (!selectedPath || fileKind !== 'text' || busy) return
    setBusy(true)
    setError('')
    try {
      await jsonOrThrow(
        await api.projects.writeFile(project.id, selectedPath, content),
        'File save failed:',
      )
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
      await openFile({ path: requested, type: 'file' })
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
      await jsonOrThrow(
        await api.projects.writeBytes(project.id, target, await file.arrayBuffer()),
        'Upload failed:',
      )
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
    if (busy) return
    if (!window.confirm(`Delete “${project.name}” and its project chat?`)) return
    setBusy(true)
    setError('')
    const deleted = await onDelete(project)
    if (!deleted) setBusy(false)
  }

  const breadcrumb = useMemo(() => path.split('/').filter(Boolean), [path])

  return (
    <section className="project-workspace" aria-label={`${project.name} project`}>
      <header className="project-workspace__header">
        <div className="project-workspace__identity">
          <span className="project-workspace__mark" aria-hidden="true">{project.name.slice(0, 1).toUpperCase()}</span>
          <div>
            <h1>{project.name}</h1>
            <p>{project.template?.name || project.project_type}</p>
          </div>
        </div>
        <div className="project-workspace__header-actions">
          <button type="button" className="project-workspace__delete" disabled={busy} onClick={deleteProject}>
            Delete
          </button>
          <button
            type="button"
            className="project-workspace__chat"
            aria-label="Open project chat"
            title="Open project chat"
            onClick={() => onOpenChat(project.chat_id)}
          >
            Chat
          </button>
        </div>
      </header>
      {((project.template?.previews || []).length > 0 || (project.template?.actions || []).length > 0) && (
        <div className="project-workspace__tools" aria-label="Project tools">
          <span>Project tools</span>
          {(project.template?.previews || []).map(preview => (
            <button key={preview.id} type="button" className="project-workspace__secondary" disabled={busy} onClick={() => openPreview(preview)}>
              {preview.name}
            </button>
          ))}
          {(project.template?.actions || []).map(action => (
            <button key={action.id} type="button" className="project-workspace__secondary" onClick={() => onRunAction(project, action)}>
              {action.name}
            </button>
          ))}
        </div>
      )}
      <div className="project-workspace__body">
        <aside className="project-files" aria-label="Project files">
          <div className="project-files__toolbar">
            <div className="project-files__breadcrumb" title={path || 'Project root'}>
              <button type="button" onClick={() => setPath('')} disabled={!path}>Project</button>
              {breadcrumb.map((part, index) => (
                <span key={`${part}:${index}`}>/ {part}</span>
              ))}
            </div>
            <div className="project-files__actions">
              <button type="button" onClick={createFile} disabled={busy}>New file</button>
              <button type="button" onClick={() => uploadRef.current?.click()} disabled={busy}>Upload</button>
              <input ref={uploadRef} type="file" hidden onChange={uploadFile} />
            </div>
          </div>
          {path && (
            <button type="button" className="project-files__row project-files__row--back" onClick={() => setPath(parentPath(path))}>
              <span aria-hidden="true">←</span><span>Parent folder</span>
            </button>
          )}
          {filesQuery.isLoading ? (
            <p className="project-files__status">Loading files…</p>
          ) : filesQuery.isError ? (
            <button type="button" className="project-files__status" onClick={() => filesQuery.refetch()}>Retry file list</button>
          ) : entries.length === 0 ? (
            <p className="project-files__status">This folder is empty.</p>
          ) : entries.map(entry => (
            <button
              key={entry.path}
              type="button"
              className={`project-files__row${selectedPath === entry.path ? ' project-files__row--active' : ''}`}
              onClick={() => openFile(entry)}
            >
              <span className="project-files__kind" aria-hidden="true">{entry.type === 'directory' ? '▸' : '·'}</span>
              <span>{entry.name}</span>
              {entry.type === 'file' && <small>{entry.size < 1024 ? `${entry.size} B` : `${Math.ceil(entry.size / 1024)} KB`}</small>}
            </button>
          ))}
        </aside>
        <article className="project-editor">
          {openItems.length > 0 && (
            <div className="project-editor__tabs" role="tablist" aria-label="Open project files and previews">
              {openItems.map(item => (
                <div
                  key={item.key}
                  role="tab"
                  aria-selected={item.key === activeItemKey}
                  className={`project-editor__tab${item.key === activeItemKey ? ' project-editor__tab--active' : ''}`}
                >
                  <button type="button" onClick={() => activateItem(item)}>{item.name}</button>
                  <button type="button" aria-label={`Close ${item.name}`} onClick={event => closeItem(event, item)}>×</button>
                </div>
              ))}
            </div>
          )}
          {selectedPath ? (
            <>
              <div className="project-editor__toolbar">
                <strong title={selectedPath}>{selectedPath}</strong>
                <div>
                  {['binary', 'image', 'pdf'].includes(fileKind) && <button type="button" onClick={downloadFile}>Download</button>}
                  {fileKind === 'text' && <button type="button" disabled={!dirty || busy} onClick={saveFile}>{busy ? 'Saving…' : 'Save'}</button>}
                </div>
              </div>
              {error && <p className="projects-error" role="alert">{error}</p>}
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
                <div className="project-preview">
                  <p>Safe preview · scripts, network requests, forms, and parent access are disabled.</p>
                  <iframe title={`${selectedPath} preview`} sandbox={projectPreviewSandbox()} srcDoc={content} />
                </div>
              ) : fileKind === 'image' ? (
                <div className="project-preview project-preview--asset">
                  <img src={objectUrl || ''} alt={`Preview of ${selectedPath}`} />
                </div>
              ) : fileKind === 'pdf' ? (
                <div className="project-preview project-preview--asset">
                  <iframe title={`${selectedPath} PDF`} src={objectUrl || ''} />
                </div>
              ) : fileKind === 'binary' ? (
                <div className="project-editor__empty">
                  <h2>Binary file</h2>
                  <p>This asset is preserved as-is. Download it to inspect or edit it locally.</p>
                  <button type="button" onClick={downloadFile}>Download {selectedPath.split('/').pop()}</button>
                </div>
              ) : (
                <div className="project-editor__empty"><p>Opening file…</p></div>
              )}
            </>
          ) : (
            <div className="project-editor__empty">
              <span aria-hidden="true">{project.name.slice(0, 1).toUpperCase()}</span>
              <h2>{project.name}</h2>
              <p>Select a file, or open the project chat beside this pane to start building.</p>
              <button type="button" onClick={() => onOpenChat(project.chat_id)}>Open project chat</button>
            </div>
          )}
        </article>
      </div>
    </section>
  )
}
