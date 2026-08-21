import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Boxes from 'lucide-react/dist/esm/icons/boxes.mjs'
import ChevronRight from 'lucide-react/dist/esm/icons/chevron-right.mjs'
import Plus from 'lucide-react/dist/esm/icons/plus.mjs'
import Sigma from 'lucide-react/dist/esm/icons/sigma.mjs'
import PanelsTopLeft from 'lucide-react/dist/esm/icons/panels-top-left.mjs'
import { api, jsonOrThrow } from '../../api/client.js'
import { projectQueries } from '../../hooks/queries.js'
import { artifactStatusPill, normalizeArtifacts } from '../../lib/projectArtifacts.js'
import './Projects.css'

const BUILDERS = [
  { key: 'website', label: 'Website', hint: 'index.html' },
  { key: 'latex', label: 'LaTeX', hint: 'main.tex' },
]

// The Artifacts zone of a project workspace: lists buildable outputs (website /
// latex), each opening in its own tab, plus a compact "New artifact" form.
export default function ProjectArtifacts({ projectId, onOpen }) {
  const artifactsQuery = useQuery({
    queryKey: projectQueries.keys.artifacts(projectId),
    queryFn: async ({ signal }) => normalizeArtifacts(await jsonOrThrow(
      await api.projects.artifacts(projectId, { signal }),
      'Project artifacts failed:',
    )),
  })
  const artifacts = artifactsQuery.data || []
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState({ name: '', builder: 'website', source: 'index.html' })

  const canSubmit = useMemo(
    () => draft.name.trim() && draft.source.trim() && !busy,
    [draft, busy],
  )

  async function submit(event) {
    event.preventDefault()
    if (!canSubmit) return
    setBusy(true); setError('')
    try {
      await jsonOrThrow(await api.projects.createArtifact(projectId, {
        name: draft.name.trim(),
        builder: draft.builder,
        source: draft.source.trim(),
      }), 'Artifact creation failed:')
      setAdding(false)
      setDraft({ name: '', builder: 'website', source: 'index.html' })
      await artifactsQuery.refetch()
    } catch (cause) {
      setError(cause?.message || 'Could not create that artifact.')
    } finally { setBusy(false) }
  }

  return (
    <section className="project-artifacts" aria-labelledby="project-artifacts-label">
      <div className="project-section-heading">
        <h2 id="project-artifacts-label"><Boxes size={16} aria-hidden="true" /> Artifacts</h2>
        <button type="button" className="project-finder__tool" aria-expanded={adding} onClick={() => { setAdding(v => !v); setError('') }}>
          <Plus size={15} aria-hidden="true" /> New artifact
        </button>
      </div>

      {adding && (
        <form className="project-artifacts__create" onSubmit={submit} onKeyDown={e => { if (e.key === 'Escape' && !busy) setAdding(false) }}>
          <input
            aria-label="Artifact name"
            placeholder="Name"
            autoFocus
            maxLength={128}
            value={draft.name}
            onChange={e => setDraft(d => ({ ...d, name: e.target.value }))}
          />
          <select
            aria-label="Builder"
            value={draft.builder}
            onChange={e => setDraft(d => ({
              ...d,
              builder: e.target.value,
              source: BUILDERS.find(b => b.key === e.target.value)?.hint || d.source,
            }))}
          >
            {BUILDERS.map(b => <option key={b.key} value={b.key}>{b.label}</option>)}
          </select>
          <input
            aria-label="Source file"
            placeholder="source file"
            maxLength={512}
            value={draft.source}
            onChange={e => setDraft(d => ({ ...d, source: e.target.value }))}
          />
          <button type="submit" disabled={!canSubmit}>{busy ? 'Adding…' : 'Add'}</button>
          <button type="button" disabled={busy} onClick={() => setAdding(false)}>Cancel</button>
        </form>
      )}

      {error && <p className="projects-error" role="alert">{error}</p>}

      {artifactsQuery.isLoading ? (
        <p className="projects-empty" role="status">Loading artifacts…</p>
      ) : artifactsQuery.isError ? (
        <div className="projects-empty" role="alert"><p>Artifacts are unavailable.</p><button type="button" onClick={() => artifactsQuery.refetch()}>Try again</button></div>
      ) : artifacts.length === 0 ? (
        <p className="projects-empty project-artifacts__empty">No artifacts yet. A website or LaTeX build shows up here.</p>
      ) : (
        <div className="project-artifacts__list">
          {artifacts.map(artifact => {
            const pill = artifactStatusPill(artifact)
            return (
              <button key={artifact.id} type="button" className="project-artifacts__row" onClick={() => onOpen?.(artifact.id)}>
                <span className="project-artifacts__icon" aria-hidden="true">
                  {artifact.builder === 'latex' ? <Sigma size={20} /> : <PanelsTopLeft size={20} />}
                </span>
                <span className="project-artifacts__copy">
                  <strong>{artifact.name || artifact.id}</strong>
                  <small>{artifact.builder === 'latex' ? 'LaTeX document' : 'Website'}{artifact.source ? ` · ${artifact.source}` : ''}</small>
                </span>
                <span className={`artifact-pill artifact-pill--${pill.variant}`}>{pill.label}</span>
                <ChevronRight size={16} aria-hidden="true" className="project-artifacts__chevron" />
              </button>
            )
          })}
        </div>
      )}
    </section>
  )
}
