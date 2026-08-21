import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import DOMPurify from 'dompurify'
import ArrowLeft from 'lucide-react/dist/esm/icons/arrow-left.mjs'
import ChevronRight from 'lucide-react/dist/esm/icons/chevron-right.mjs'
import Download from 'lucide-react/dist/esm/icons/download.mjs'
import Ellipsis from 'lucide-react/dist/esm/icons/ellipsis.mjs'
import File from 'lucide-react/dist/esm/icons/file.mjs'
import FileCode from 'lucide-react/dist/esm/icons/file-code.mjs'
import FileText from 'lucide-react/dist/esm/icons/file-text.mjs'
import Folder from 'lucide-react/dist/esm/icons/folder.mjs'
import FolderPlus from 'lucide-react/dist/esm/icons/folder-plus.mjs'
import Hammer from 'lucide-react/dist/esm/icons/hammer.mjs'
import Image from 'lucide-react/dist/esm/icons/image.mjs'
import Pencil from 'lucide-react/dist/esm/icons/pencil.mjs'
import Upload from 'lucide-react/dist/esm/icons/upload.mjs'
import Trash2 from 'lucide-react/dist/esm/icons/trash-2.mjs'
import { api, jsonOrThrow } from '../../api/client.js'
import { projectQueries } from '../../hooks/queries.js'
import { assembleProjectHtmlPreview, projectPreviewSandbox } from '../../lib/projectPreview.js'
import { useHistoryDismissControls } from '../../hooks/useHistoryDismiss.jsx'
import {
  back as finderBack,
  finderCrumbs,
  initFinder,
  joinPath,
  openFile as finderOpenFile,
  openFolder as finderOpenFolder,
  parentPath,
} from '../../lib/projectFinderNav.js'
import ProjectPdfPreview from './ProjectPdfPreview.jsx'
import ImageLightbox from '../ChatView/markdown/ImageLightbox.jsx'
import { highlightCode } from '../ChatView/markdown/highlight.js'
import './Projects.css'

// A scan that settles inside this window swaps content with no spinner at all —
// only a genuinely slow read surfaces the indicator (deepseek-harness pattern).
const SLOW_SCAN_DELAY_MS = 300
// Highlighting/rendering the whole of a very large file janks the tab; window it
// to the head and offer Download for the rest (Möbius users pay their own CPU).
const WINDOW_CHARS = 200_000

const CODE_EXTS = new Set([
  'html', 'htm', 'css', 'js', 'jsx', 'ts', 'tsx', 'mjs', 'cjs', 'json', 'py',
  'sh', 'bash', 'yml', 'yaml', 'toml', 'sql', 'rs', 'go', 'java', 'c', 'cpp',
  'h', 'xml', 'svg',
])
// A file becomes a build artifact purely by its extension — dumb-simple, no
// scanning or guessing. Only these known kinds get a "Build as …" action.
const ARTIFACT_BUILDERS = { html: 'website', htm: 'website', tex: 'latex' }
const ARTIFACT_BUILD_LABEL = { website: 'Build as website', latex: 'Build as PDF' }
function builderForFile(name) {
  return ARTIFACT_BUILDERS[(name.split('.').pop() || '').toLowerCase()] || null
}
const HLJS_LANG = {
  js: 'javascript', jsx: 'javascript', mjs: 'javascript', cjs: 'javascript',
  ts: 'typescript', tsx: 'typescript', py: 'python', sh: 'bash', bash: 'bash',
  yml: 'yaml', html: 'xml', htm: 'xml', svg: 'xml', json: 'json', css: 'css',
  sql: 'sql',
}

function extensionOf(path) {
  return String(path ?? '').split('.').pop()?.toLowerCase() || ''
}

function entryIcon(entry, size) {
  if (entry.type === 'directory') return <Folder size={size} />
  const ext = extensionOf(entry.name)
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'avif'].includes(ext)) return <Image size={size} />
  if (CODE_EXTS.has(ext)) return <FileCode size={size} />
  if (['md', 'txt', 'tex', 'csv', 'pdf'].includes(ext)) return <FileText size={size} />
  return <File size={size} />
}

function formatSize(bytes) {
  if (!Number.isFinite(bytes)) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// The Finder: a breadcrumb bar over a list (mobile) or list + preview pane
// (desktop, container-query driven), with in-place inspection that never leaves
// the tab. Folder + file navigation is wired into the shell's history stack so
// the browser Back button walks back through it in-tab.
export default function ProjectFinder({ projectId, projectName, onBuildFile }) {
  const history = useHistoryDismissControls()
  const [nav, setNav] = useState(() => initFinder())
  const path = nav.current.path
  const selected = nav.current.selected

  // Parallel stack of history entry ids, one per forward step, popped LIFO by
  // Back or by the in-UI back controls so history and nav stay in sync.
  const entryStackRef = useRef([])
  const navRef = useRef(nav)
  navRef.current = nav

  // Browser Back / swipe consumes the top sentinel and lands here: pop one nav
  // step. Stable identity — every sentinel shares it (Back always pops the top).
  const onHistoryPop = useCallback(() => {
    entryStackRef.current.pop()
    const next = finderBack(navRef.current).state
    navRef.current = next
    setNav(next)
  }, [])

  // A forward step (open folder / open file / crumb jump). Compute the transition
  // from the current nav, then — only for a real change — push one history
  // sentinel so the browser Back button retraces it in-tab. The history push is
  // kept OUT of the setState updater (updaters must stay pure / StrictMode-safe).
  const goForward = useCallback((compute) => {
    const { state, pushed } = compute(navRef.current)
    if (!pushed) return
    navRef.current = state
    setNav(state)
    if (history?.open) {
      const id = history.open(onHistoryPop)
      if (id) entryStackRef.current.push(id)
    }
  }, [history, onHistoryPop])

  // The in-UI back controls (parent folder, close file, breadcrumb-up) go
  // through the SAME pop path as the browser Back button by consuming the top
  // sentinel, whose dismissal calls onHistoryPop.
  const goBack = useCallback(() => {
    const id = entryStackRef.current[entryStackRef.current.length - 1]
    if (id && history?.close) history.close(id)
    else setNav(current => finderBack(current).state)
  }, [history])

  const openFolder = useCallback((next) => goForward(s => finderOpenFolder(s, next)), [goForward])
  const openFileAt = useCallback((filePath) => goForward(s => finderOpenFile(s, filePath)), [goForward])

  // Reset the finder for a new project, and on unmount / project switch release
  // its history sentinels without a traversal (just drop the registrations).
  useEffect(() => {
    navRef.current = initFinder()
    setNav(initFinder())
    return () => {
      for (const id of entryStackRef.current) history?.unregister?.(id)
      entryStackRef.current = []
    }
  }, [projectId, history])

  // ── Folder listing: keep the stale view while the next folder loads, and only
  // reveal a spinner if the scan stays silent past SLOW_SCAN_DELAY_MS.
  const filesQuery = useQuery({
    queryKey: projectQueries.keys.files(projectId, path),
    queryFn: async ({ signal }) => jsonOrThrow(
      await api.projects.files(projectId, path, { signal }),
      'Project files failed:',
    ),
    placeholderData: keepPreviousData,
  })
  const entries = filesQuery.data?.entries || []
  const [slowScan, setSlowScan] = useState(false)
  useEffect(() => {
    if (!filesQuery.isFetching) { setSlowScan(false); return undefined }
    const timer = setTimeout(() => setSlowScan(true), SLOW_SCAN_DELAY_MS)
    return () => clearTimeout(timer)
  }, [filesQuery.isFetching])

  // Tail-pin the breadcrumb: deep paths overflow, keep the current directory in
  // view whenever the chain grows.
  const crumbTrailRef = useRef(null)
  const crumbs = useMemo(() => finderCrumbs(projectName, path), [projectName, path])
  useEffect(() => {
    const el = crumbTrailRef.current
    if (el) el.scrollLeft = el.scrollWidth
  }, [crumbs])

  // ── Inspection surface state (driven by `selected`) ─────────────────────────
  const [fileKind, setFileKind] = useState('none') // none|text|html|image|pdf|binary|error
  const [content, setContent] = useState('')
  const [baseline, setBaseline] = useState('')
  const [objectUrl, setObjectUrl] = useState(null)
  const [pdfData, setPdfData] = useState(null)
  const [fileError, setFileError] = useState('')
  const [fileLoading, setFileLoading] = useState(false)
  const [editing, setEditing] = useState(false)
  const [highlighted, setHighlighted] = useState(null)
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const dirty = fileKind === 'text' && editing && content !== baseline

  const objectUrlRef = useRef(null)
  const replaceObjectUrl = useCallback((next) => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current)
    objectUrlRef.current = next
    setObjectUrl(next)
  }, [])
  useEffect(() => () => { if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current) }, [])

  const windowed = fileKind === 'text' && content.length > WINDOW_CHARS
  const codeLike = selected && CODE_EXTS.has(extensionOf(selected))

  // Load whatever `selected` names. Supersede an in-flight read (AbortController)
  // and keep the previously-shown file until the new one arrives.
  useEffect(() => {
    if (!selected) {
      setFileKind('none'); setContent(''); setBaseline(''); setHighlighted(null)
      setPdfData(null); replaceObjectUrl(null); setFileError(''); setEditing(false)
      return undefined
    }
    const controller = new AbortController()
    let active = true
    setFileError('')
    setEditing(false)
    const spinner = setTimeout(() => { if (active) setFileLoading(true) }, SLOW_SCAN_DELAY_MS)
    ;(async () => {
      try {
        const res = await api.projects.readFile(projectId, selected, { signal: controller.signal })
        if (!active) return
        const type = res.headers.get('content-type') || ''
        if (type.includes('application/json')) {
          const data = await jsonOrThrow(res, 'File open failed:')
          if (!active) return
          if (extensionOf(selected) === 'html') {
            const assembled = await assembleProjectHtmlPreview(
              data.content, selected,
              async dep => (await jsonOrThrow(
                await api.projects.readFile(projectId, dep), 'Preview dependency failed:',
              )).content,
            )
            if (!active) return
            setContent(assembled); setBaseline(''); setFileKind('html')
          } else {
            setContent(data.content); setBaseline(data.content); setFileKind('text')
          }
          setPdfData(null); replaceObjectUrl(null)
        } else if (res.ok) {
          const blob = await res.blob()
          if (!active) return
          const isPdf = blob.type === 'application/pdf' || selected.toLowerCase().endsWith('.pdf')
          if (isPdf) {
            replaceObjectUrl(null)
            setPdfData(new Uint8Array(await blob.arrayBuffer())); setFileKind('pdf')
          } else if (blob.type.startsWith('image/')) {
            setPdfData(null); replaceObjectUrl(URL.createObjectURL(blob)); setFileKind('image')
          } else {
            setPdfData(null); replaceObjectUrl(URL.createObjectURL(blob)); setFileKind('binary')
          }
          setContent(''); setBaseline('')
        } else {
          throw new Error(`File open failed: ${res.status}`)
        }
      } catch (cause) {
        if (!active || cause?.name === 'AbortError') return
        setFileError(cause?.message || 'Could not open that file.')
        setFileKind('error')
      } finally {
        if (active) setFileLoading(false)
      }
    })()
    return () => { active = false; controller.abort(); clearTimeout(spinner) }
  }, [projectId, selected, replaceObjectUrl])

  // Lazy syntax highlight for the read view of a code file (windowed head only).
  useEffect(() => {
    setHighlighted(null)
    if (fileKind !== 'text' || editing || !codeLike || !content) return
    let active = true
    const slice = content.length > WINDOW_CHARS ? content.slice(0, WINDOW_CHARS) : content
    const lang = HLJS_LANG[extensionOf(selected)]
    // highlight.js already escapes the code text; DOMPurify is defense-in-depth
    // before dangerouslySetInnerHTML (same posture as the markdown CodeBlock).
    highlightCode(slice, lang).then(html => { if (active && html) setHighlighted(DOMPurify.sanitize(html)) })
    return () => { active = false }
  }, [fileKind, editing, codeLike, content, selected])

  // ── File mutations ──────────────────────────────────────────────────────────
  const refetchFiles = useCallback(() => filesQuery.refetch(), [filesQuery])

  async function saveFile() {
    if (fileKind !== 'text' || busy || !dirty) return
    setBusy(true); setError('')
    try {
      await jsonOrThrow(await api.projects.writeFile(projectId, selected, content), 'File save failed:')
      setBaseline(content); setEditing(false)
      await refetchFiles()
    } catch (cause) {
      setError(cause?.message || 'Could not save that file.')
    } finally { setBusy(false) }
  }

  async function downloadFile(target = selected) {
    if (!target) return
    try {
      const res = await api.projects.readFile(projectId, target, { download: true })
      if (!res.ok) throw new Error(`Download failed: ${res.status}`)
      const url = URL.createObjectURL(await res.blob())
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = target.split('/').pop()
      anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 0)
    } catch (cause) {
      setError(cause?.message || 'Could not download that file.')
    }
  }

  async function deleteEntry(entryPath) {
    if (busy || !window.confirm(`Delete “${entryPath}”?`)) return
    setBusy(true); setError('')
    try {
      await jsonOrThrow(await api.projects.deleteFile(projectId, entryPath), 'File deletion failed:')
      if (selected === entryPath) goBack()
      await refetchFiles()
    } catch (cause) {
      setError(cause?.message || 'Could not delete that.')
    } finally { setBusy(false) }
  }

  // Rename + move both go through POST /{id}/move — rename keeps the parent dir,
  // move retargets it. `to` is the full destination path.
  async function moveEntry(from, to) {
    const target = String(to || '').trim()
    if (!target || target === from) return true
    setBusy(true); setError('')
    try {
      await jsonOrThrow(await api.projects.move(projectId, { from_path: from, to_path: target }), 'Move failed:')
      if (selected === from) {
        // The inspected file moved — follow it so the preview stays coherent.
        setNav(current => ({ ...current, current: { ...current.current, selected: target } }))
      }
      await refetchFiles()
      return true
    } catch (cause) {
      setError(cause?.message || 'Could not move that.')
      return false
    } finally { setBusy(false) }
  }

  // ── Create / upload ───────────────────────────────────────────────────────
  const [creation, setCreation] = useState(null) // 'file' | 'folder' | null
  const [creationName, setCreationName] = useState('')
  const uploadRef = useRef(null)
  async function submitCreate(event) {
    event.preventDefault()
    const name = creationName.trim()
    if (!name || !creation || busy) return
    const target = joinPath(path, name)
    setBusy(true); setError('')
    try {
      if (creation === 'file') {
        await jsonOrThrow(await api.projects.writeFile(projectId, target, ''), 'File creation failed:')
      } else {
        await jsonOrThrow(await api.projects.createFolder(projectId, target), 'Folder creation failed:')
      }
      setCreation(null); setCreationName('')
      await refetchFiles()
      if (creation === 'file') openFileAt(target)
    } catch (cause) {
      setError(cause?.message || `Could not create that ${creation}.`)
    } finally { setBusy(false) }
  }
  async function uploadFiles(event) {
    const files = [...(event.target.files || [])]
    event.target.value = ''
    if (files.length === 0) return
    setBusy(true); setError('')
    try {
      for (const file of files) {
        await jsonOrThrow(
          await api.projects.writeBytes(projectId, joinPath(path, file.name), await file.arrayBuffer()),
          `Upload of ${file.name} failed:`,
        )
      }
      await refetchFiles()
    } catch (cause) {
      setError(cause?.message || 'Could not upload that file.')
    } finally { setBusy(false) }
  }

  const inspecting = !!selected
  const selectedName = selected ? selected.split('/').pop() : ''

  return (
    <section className="project-finder" aria-label={`${projectName} files`} data-inspecting={inspecting || undefined}>
      <nav className="project-finder__crumbs" aria-label="Folder location" ref={crumbTrailRef}>
        {crumbs.map((crumb, index) => (
          <span key={crumb.path || 'root'} className="project-finder__crumb">
            {index > 0 && <ChevronRight size={13} aria-hidden="true" />}
            <button
              type="button"
              aria-current={index === crumbs.length - 1 && !selected ? 'page' : undefined}
              onClick={() => openFolder(crumb.path)}
            >
              {crumb.label}
            </button>
          </span>
        ))}
        {slowScan && <span className="project-finder__scan" role="status">Loading…</span>}
      </nav>

      <div className="project-finder__toolbar" role="toolbar" aria-label="File actions">
        {path && (
          <button type="button" className="project-finder__tool" onClick={goBack}>
            <ArrowLeft size={15} aria-hidden="true" /> Up
          </button>
        )}
        <span className="project-finder__toolbar-spacer" />
        <button type="button" className="project-finder__tool" disabled={busy} onClick={() => { setCreation('file'); setCreationName('') }}>
          <FileText size={15} aria-hidden="true" /> New file
        </button>
        <button type="button" className="project-finder__tool" disabled={busy} onClick={() => { setCreation('folder'); setCreationName('') }}>
          <FolderPlus size={15} aria-hidden="true" /> New folder
        </button>
        <button type="button" className="project-finder__tool" disabled={busy} onClick={() => uploadRef.current?.click()}>
          <Upload size={15} aria-hidden="true" /> Upload
        </button>
        <input ref={uploadRef} type="file" multiple hidden onChange={uploadFiles} />
      </div>

      {creation && (
        <form className="project-inline-create" onSubmit={submitCreate} onKeyDown={e => { if (e.key === 'Escape' && !busy) setCreation(null) }}>
          <label htmlFor="project-finder-create">{creation === 'file' ? 'New file' : 'New folder'}</label>
          <input
            id="project-finder-create"
            autoFocus
            value={creationName}
            maxLength={2048}
            placeholder={path ? `${path}/name` : 'name'}
            onChange={e => setCreationName(e.target.value)}
          />
          <button type="submit" disabled={busy || !creationName.trim()}>{busy ? 'Creating…' : 'Create'}</button>
          <button type="button" disabled={busy} onClick={() => setCreation(null)}>Cancel</button>
        </form>
      )}

      {error && <p className="projects-error" role="alert">{error}</p>}

      <div className="project-finder__body">
        <div className="project-finder__list" role="list" aria-label={`Files in ${path || projectName}`}>
          {filesQuery.isLoading ? (
            <p className="projects-empty" role="status">Loading files…</p>
          ) : filesQuery.isError ? (
            <div className="projects-empty" role="alert"><p>Files are unavailable.</p><button type="button" onClick={() => filesQuery.refetch()}>Try again</button></div>
          ) : entries.length === 0 ? (
            <p className="projects-empty">This folder is empty.</p>
          ) : (
            entries.map(entry => (
              <FinderRow
                key={entry.path}
                entry={entry}
                active={entry.path === selected}
                disabled={busy}
                onOpen={() => (entry.type === 'directory' ? openFolder(entry.path) : openFileAt(entry.path))}
                onRename={(next) => moveEntry(entry.path, joinPath(parentPath(entry.path), next))}
                onMove={(toDir) => moveEntry(entry.path, joinPath(toDir, entry.name))}
                onDownload={() => downloadFile(entry.path)}
                onDelete={() => deleteEntry(entry.path)}
                onBuildAs={onBuildFile ? (builder) => onBuildFile(entry.path, builder) : null}
              />
            ))
          )}
        </div>

        <div className="project-finder__pane" aria-live="polite">
          {!inspecting ? (
            <div className="project-finder__placeholder" role="status">
              <File size={38} strokeWidth={1.3} aria-hidden="true" />
              <p>Select a file to preview it here.</p>
            </div>
          ) : (
            <>
              <header className="project-finder__pane-head">
                <button type="button" className="project-icon-button project-finder__pane-back" aria-label="Back to files" onClick={goBack}><ArrowLeft size={18} /></button>
                <div><strong>{selectedName}</strong><small>{selected}</small></div>
                <div className="project-finder__pane-actions">
                  {['image', 'pdf', 'binary'].includes(fileKind) && (
                    <button type="button" onClick={() => downloadFile()}>Download</button>
                  )}
                  {fileKind === 'text' && !windowed && !editing && (
                    <button type="button" onClick={() => setEditing(true)}><Pencil size={14} aria-hidden="true" /> Edit</button>
                  )}
                  {fileKind === 'text' && editing && (
                    <button type="button" disabled={!dirty || busy} onClick={saveFile}>{busy ? 'Saving…' : 'Save'}</button>
                  )}
                </div>
              </header>
              {fileError && <p className="projects-error" role="alert">{fileError}</p>}
              <div className="project-finder__surface">
                {fileLoading && fileKind === 'none' ? (
                  <div className="project-document__empty" role="status"><p>Opening file…</p></div>
                ) : fileKind === 'text' ? (
                  editing && !windowed ? (
                    <textarea
                      aria-label={`Edit ${selected}`}
                      value={content}
                      spellCheck="false"
                      onChange={e => setContent(e.target.value)}
                      onKeyDown={e => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); void saveFile() } }}
                    />
                  ) : (
                    <div className="project-finder__code">
                      {windowed && <p className="project-finder__notice" role="status">Large file — showing the first {Math.round(WINDOW_CHARS / 1000)}K characters. Download to see all of it.</p>}
                      {highlighted
                        ? <pre className="hljs"><code dangerouslySetInnerHTML={{ __html: highlighted }} /></pre>
                        : <pre><code>{windowed ? content.slice(0, WINDOW_CHARS) : content}</code></pre>}
                    </div>
                  )
                ) : fileKind === 'html' ? (
                  <div className="project-preview">
                    <p>Isolated preview · local scripts and styles can run; network, forms, downloads, and parent access are blocked.</p>
                    <iframe title={`${selected} preview`} sandbox={projectPreviewSandbox()} srcDoc={content} />
                  </div>
                ) : fileKind === 'image' ? (
                  <div className="project-preview project-preview--asset">
                    <button type="button" className="project-finder__image-btn" onClick={() => setLightboxOpen(true)} aria-label={`Zoom ${selectedName}`}>
                      <img src={objectUrl || ''} alt={`Preview of ${selected}`} />
                    </button>
                  </div>
                ) : fileKind === 'pdf' ? (
                  <ProjectPdfPreview data={pdfData} title={selected} />
                ) : fileKind === 'binary' ? (
                  <div className="project-document__empty"><File size={42} strokeWidth={1.4} /><h2>Preview unavailable</h2><p>This file is preserved as-is and can be downloaded.</p><button type="button" onClick={() => downloadFile()}>Download</button></div>
                ) : fileKind === 'error' ? (
                  <div className="project-document__empty" role="alert"><File size={42} strokeWidth={1.4} /><h2>Couldn’t open this file</h2><p>{fileError || 'The file may have moved or become unavailable.'}</p></div>
                ) : (
                  <div className="project-document__empty" role="status"><p>Opening file…</p></div>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {lightboxOpen && objectUrl && createPortal(
        <ImageLightbox src={objectUrl} alt={selectedName} onClose={() => setLightboxOpen(false)} />,
        document.body,
      )}
    </section>
  )
}

// One entry row with a context action menu (open / rename / move / download /
// delete). Rename + move both call POST /{id}/move via the parent.
function FinderRow({ entry, active, disabled, onOpen, onRename, onMove, onDownload, onDelete, onBuildAs }) {
  const [menu, setMenu] = useState(false)
  const [mode, setMode] = useState(null) // 'rename' | 'move' | null
  const [value, setValue] = useState('')
  const rootRef = useRef(null)
  const isDir = entry.type === 'directory'

  useEffect(() => {
    if (!menu) return undefined
    function onPointer(e) { if (!rootRef.current?.contains(e.target)) setMenu(false) }
    function onEsc(e) { if (e.key === 'Escape') setMenu(false) }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onEsc)
    return () => { document.removeEventListener('pointerdown', onPointer); document.removeEventListener('keydown', onEsc) }
  }, [menu])

  function begin(next) {
    setMenu(false)
    setMode(next)
    setValue(next === 'rename' ? entry.name : '')
  }
  async function submit(e) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed) { setMode(null); return }
    const ok = mode === 'rename' ? await onRename(trimmed) : await onMove(trimmed)
    if (ok !== false) setMode(null)
  }

  if (mode) {
    return (
      <form className="project-finder__rename" onSubmit={submit} onKeyDown={e => { if (e.key === 'Escape') setMode(null) }}>
        <label>{mode === 'rename' ? 'Rename to' : 'Move to folder'}</label>
        <input autoFocus value={value} maxLength={2048} placeholder={mode === 'move' ? 'destination/folder' : entry.name} onChange={e => setValue(e.target.value)} />
        <button type="submit" disabled={disabled}>Save</button>
        <button type="button" onClick={() => setMode(null)}>Cancel</button>
      </form>
    )
  }

  return (
    <div ref={rootRef} className={`project-finder__row${active ? ' project-finder__row--active' : ''}`} role="listitem">
      <button type="button" className="project-finder__row-main" disabled={disabled} onClick={onOpen} aria-current={active ? 'true' : undefined}>
        <span className="project-finder__row-icon" aria-hidden="true">{entryIcon(entry, 19)}</span>
        <span className="project-finder__row-text"><strong>{entry.name}</strong><small>{isDir ? 'Folder' : formatSize(entry.size)}</small></span>
        {isDir && <ChevronRight size={15} className="project-finder__row-chevron" aria-hidden="true" />}
      </button>
      <div className="project-menu">
        <button type="button" className="project-icon-button project-finder__row-menu" aria-label={`Actions for ${entry.name}`} aria-haspopup="menu" aria-expanded={menu} disabled={disabled} onClick={() => setMenu(v => !v)}><Ellipsis size={17} /></button>
        {menu && (
          <div className="project-menu__popover project-menu__popover--end" role="menu">
            <button type="button" role="menuitem" onClick={() => begin('rename')}><Pencil size={15} /> Rename</button>
            <button type="button" role="menuitem" onClick={() => begin('move')}><FolderPlus size={15} /> Move…</button>
            {!isDir && <button type="button" role="menuitem" onClick={() => { setMenu(false); onDownload() }}><Download size={15} /> Download</button>}
            {!isDir && onBuildAs && builderForFile(entry.name) && (
              <button type="button" role="menuitem" onClick={() => { setMenu(false); onBuildAs(builderForFile(entry.name)) }}><Hammer size={15} /> {ARTIFACT_BUILD_LABEL[builderForFile(entry.name)]}</button>
            )}
            <button type="button" role="menuitem" className="project-menu__danger" onClick={() => { setMenu(false); onDelete() }}><Trash2 size={15} /> Delete</button>
          </div>
        )}
      </div>
    </div>
  )
}
