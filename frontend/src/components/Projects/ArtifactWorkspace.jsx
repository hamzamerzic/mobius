import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import ArrowLeft from 'lucide-react/dist/esm/icons/arrow-left.mjs'
import ChevronDown from 'lucide-react/dist/esm/icons/chevron-down.mjs'
import ChevronRight from 'lucide-react/dist/esm/icons/chevron-right.mjs'
import Hammer from 'lucide-react/dist/esm/icons/hammer.mjs'
import { api, jsonOrThrow } from '../../api/client.js'
import { projectQueries } from '../../hooks/queries.js'
import {
  artifactEntryPath,
  artifactStatus,
  artifactStatusPill,
  isBuilding,
  normalizeArtifacts,
  shouldHotSwapPreview,
} from '../../lib/projectArtifacts.js'
import ProjectPdfPreview from './ProjectPdfPreview.jsx'
import { assembleProjectHtmlPreview, projectPreviewSandbox } from '../../lib/projectPreview.js'
import './Projects.css'

// The artifact tab: a Build/Rebuild control + status pill + collapsible build
// log over a live preview. A website renders in a sandboxed iframe with NO
// allow-same-origin (its JS can never read the parent token); a latex artifact
// renders its compiled pdf through pdfjs. The preview hot-swaps on rebuild.
export default function ArtifactWorkspace({ projectId, artifactId, projectName, onOpenProject }) {
  const artifactsQuery = useQuery({
    queryKey: projectQueries.keys.artifacts(projectId),
    queryFn: async ({ signal }) => normalizeArtifacts(await jsonOrThrow(
      await api.projects.artifacts(projectId, { signal }),
      'Project artifacts failed:',
    )),
  })
  const artifact = useMemo(
    () => (artifactsQuery.data || []).find(row => String(row.id) === String(artifactId)) || null,
    [artifactsQuery.data, artifactId],
  )
  const status = artifactStatus(artifact)
  const pill = artifactStatusPill(artifact)
  const builder = artifact?.builder
  const hasOutput = !!artifact?.has_output

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [previewVersion, setPreviewVersion] = useState(0)

  // Hot-swap the preview when a build finishes (building -> ok, or a fresh ok
  // first seen). The status is owned by the query, refreshed by the build-status
  // system event Shell forwards into the artifacts cache.
  const prevStatusRef = useRef(status)
  useEffect(() => {
    const prev = prevStatusRef.current
    prevStatusRef.current = status
    if (shouldHotSwapPreview(prev, status)) setPreviewVersion(v => v + 1)
  }, [status])

  async function build() {
    if (busy || isBuilding(artifact)) return
    setBusy(true); setError('')
    try {
      await jsonOrThrow(await api.projects.buildArtifact(projectId, artifactId), 'Build failed:')
      // Optimistically flip to building; the system event + refetch reconcile the
      // terminal state and drive the preview hot-swap.
      await artifactsQuery.refetch()
    } catch (cause) {
      setError(cause?.message || 'Could not start the build.')
    } finally { setBusy(false) }
  }

  const entryPath = artifact ? artifactEntryPath(artifact) : null

  if (artifactsQuery.isLoading) {
    return <section className="artifact-workspace" aria-busy="true"><p className="projects-empty" role="status">Loading artifact…</p></section>
  }
  if (!artifact) {
    return (
      <section className="artifact-workspace">
        <div className="projects-empty" role="alert">
          <p>This artifact is no longer available.</p>
          {onOpenProject && <button type="button" onClick={onOpenProject}>Back to project</button>}
        </div>
      </section>
    )
  }

  return (
    <section className="artifact-workspace" aria-label={`${artifact.name || artifactId} artifact`}>
      <header className="artifact-workspace__header">
        {onOpenProject && (
          <button type="button" className="project-icon-button" aria-label="Back to project" title={projectName ? `Back to ${projectName}` : 'Back to project'} onClick={onOpenProject}><ArrowLeft size={18} /></button>
        )}
        <div className="artifact-workspace__identity">
          <strong>{artifact.name || artifactId}</strong>
          <small>{builder === 'latex' ? 'LaTeX document' : 'Website'}{projectName ? ` · ${projectName}` : ''}</small>
        </div>
        <span className={`artifact-pill artifact-pill--${pill.variant}`} role="status">{pill.label}</span>
        <button
          type="button"
          className="project-build-button"
          disabled={busy || isBuilding(artifact)}
          onClick={build}
        >
          <Hammer size={16} aria-hidden="true" />
          <span>{isBuilding(artifact) ? 'Building…' : hasOutput ? 'Rebuild' : 'Build'}</span>
        </button>
      </header>

      {error && <p className="projects-error" role="alert">{error}</p>}

      <BuildLog projectId={projectId} artifactId={artifactId} status={status} />

      <div className="artifact-workspace__surface">
        {!hasOutput && status !== 'building' ? (
          <div className="project-document__empty" role="status">
            <Hammer size={42} strokeWidth={1.3} aria-hidden="true" />
            <h2>Nothing built yet</h2>
            <p>{status === 'error' ? 'The last build failed — check the log above and try again.' : 'Build this artifact to preview it here.'}</p>
            <button type="button" className="project-build-button" disabled={busy} onClick={build}><Hammer size={16} aria-hidden="true" /><span>Build</span></button>
          </div>
        ) : builder === 'latex' ? (
          <LatexPreview projectId={projectId} artifactId={artifactId} entryPath={entryPath} version={previewVersion} />
        ) : (
          <WebsitePreview projectId={projectId} artifactId={artifactId} entryPath={entryPath} version={previewVersion} name={artifact.name || artifactId} />
        )}
      </div>
    </section>
  )
}

// The static-site preview. The shell fetches the built output over the
// authenticated route (Bearer) and inlines the entry's local CSS/JS into a
// self-contained srcDoc on an opaque origin — never a token-bearing src URL a
// sandboxed artifact could read from window.location. The frame is sandboxed
// allow-scripts WITHOUT allow-same-origin (real sites run; their JS cannot reach
// the owner token). Uninlined/remote refs are CSP-blocked so a missing local
// dependency stays visible rather than silently loading. A superseded fetch is
// aborted; `version` re-assembles after a rebuild (the hot-swap).
function WebsitePreview({ projectId, artifactId, entryPath, version, name }) {
  const [doc, setDoc] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const entry = entryPath || 'index.html'
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setLoading(true); setError('')
    ;(async () => {
      try {
        const res = await api.projects.artifactOutput(projectId, artifactId, entry, { signal: controller.signal })
        if (!active) return
        if (!res.ok) throw new Error(`The site could not be loaded (${res.status}).`)
        const html = await res.text()
        const loadText = async (path) => {
          const dep = await api.projects.artifactOutput(projectId, artifactId, path, { signal: controller.signal })
          if (!dep.ok) throw new Error(`dependency ${path} failed (${dep.status})`)
          return dep.text()
        }
        const assembled = await assembleProjectHtmlPreview(html, entry, loadText)
        if (active) setDoc(assembled)
      } catch (cause) {
        if (active && cause?.name !== 'AbortError') setError(cause?.message || 'The site could not be loaded.')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => { active = false; controller.abort() }
  }, [projectId, artifactId, entry, version])

  if (error) return <div className="project-document__empty" role="alert"><h2>Couldn’t load the site</h2><p>{error}</p></div>
  if (loading && !doc) return <div className="project-document__empty" role="status"><p>Loading site…</p></div>
  return (
    <div className="artifact-preview">
      <iframe
        key={`${artifactId}:${version}`}
        title={`${name} preview`}
        className="artifact-preview__frame"
        sandbox={projectPreviewSandbox()}
        srcDoc={doc}
      />
    </div>
  )
}

// The latex preview: fetch the compiled pdf bytes through the authenticated
// output route (pdfjs cannot send the Bearer itself) and render via pdfjs.
// A superseded fetch is aborted; `version` re-fetches after a rebuild.
function LatexPreview({ projectId, artifactId, entryPath, version }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setLoading(true); setError('')
    ;(async () => {
      try {
        const res = await api.projects.artifactOutput(projectId, artifactId, entryPath || 'main.pdf', { signal: controller.signal })
        if (!active) return
        if (!res.ok) throw new Error(`The document could not be loaded (${res.status}).`)
        const bytes = new Uint8Array(await res.arrayBuffer())
        if (active) setData(bytes)
      } catch (cause) {
        if (active && cause?.name !== 'AbortError') setError(cause?.message || 'The document could not be loaded.')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => { active = false; controller.abort() }
  }, [projectId, artifactId, entryPath, version])

  if (error) return <div className="project-document__empty" role="alert"><h2>Couldn’t load the document</h2><p>{error}</p></div>
  if (loading && !data) return <div className="project-document__empty" role="status"><p>Rendering document…</p></div>
  return <ProjectPdfPreview data={data} title="Artifact document" />
}

// A collapsible tail of the build log. Fetched on expand and whenever the build
// status changes (a finished build should show its final output).
function BuildLog({ projectId, artifactId, status }) {
  const [open, setOpen] = useState(false)
  const [log, setLog] = useState('')
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    try {
      const res = await api.projects.artifactLog(projectId, artifactId)
      if (!res.ok) throw new Error(`Log unavailable (${res.status}).`)
      const type = res.headers.get('content-type') || ''
      const text = type.includes('application/json')
        ? (await res.json())?.log ?? ''
        : await res.text()
      setLog(String(text || '')); setError('')
    } catch (cause) {
      setError(cause?.message || 'Could not load the build log.')
    }
  }, [projectId, artifactId])
  useEffect(() => { if (open) void load() }, [open, load, status])

  return (
    <div className="artifact-log">
      <button type="button" className="artifact-log__toggle" aria-expanded={open} onClick={() => setOpen(v => !v)}>
        {open ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronRight size={15} aria-hidden="true" />} Build log
      </button>
      {open && (
        <div className="artifact-log__body">
          {error ? <p className="projects-error" role="alert">{error}</p>
            : log ? <pre className="artifact-log__text">{log}</pre>
              : <p className="projects-empty" role="status">No build output yet.</p>}
        </div>
      )}
    </div>
  )
}
