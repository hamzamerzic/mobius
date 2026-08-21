// Pure helpers for project artifacts (the buildable website/latex outputs).
//
// Kept dependency-free (no React, no DOM, no api client) so the artifact-tab
// state machine is unit-testable and the same rules drive the Artifacts list,
// the ArtifactWorkspace preview, and the build-status live update.

// Lenient read: the backend may return a bare array OR an envelope, and an
// agent may hand-edit `artifacts_json` into something malformed. Never throw —
// keep only the well-formed rows so a single bad entry can't blank the list.
export function normalizeArtifacts(data) {
  const rows = Array.isArray(data)
    ? data
    : (Array.isArray(data?.artifacts) ? data.artifacts : [])
  return rows.filter(row => (
    row && typeof row === 'object'
    && typeof row.id === 'string' && row.id.length > 0
  ))
}

// The four build states map to a small status vocabulary the pill renders.
// An unknown/absent status reads as idle rather than erroring.
export function artifactStatus(artifact) {
  const status = artifact?.status
  return ['idle', 'building', 'ok', 'error'].includes(status) ? status : 'idle'
}

export function isBuilding(artifact) {
  return artifactStatus(artifact) === 'building'
}

// Human label + a semantic variant for the status pill. Variants are stable
// class suffixes (`.artifact-pill--<variant>`), not colors, so the stylesheet
// owns the palette.
export function artifactStatusPill(artifact) {
  switch (artifactStatus(artifact)) {
    case 'building': return { label: 'Building…', variant: 'building' }
    case 'ok': return { label: 'Built', variant: 'ok' }
    case 'error': return { label: 'Build failed', variant: 'error' }
    default: return { label: 'Not built', variant: 'idle' }
  }
}

// The last path segment without its extension, e.g. `paper/main.tex` -> `main`.
export function fileStem(path) {
  const base = String(path ?? '').split('/').pop() || ''
  const dot = base.lastIndexOf('.')
  return dot > 0 ? base.slice(0, dot) : base
}

// The path WITHIN `artifacts/<id>/output/` that the preview should load.
//   website -> index.html (the build copies the source tree, entry is index.html)
//   latex   -> the compiled pdf: prefer the backend's output_rel basename when it
//              already names a .pdf, else derive `<source-stem>.pdf` (tectonic
//              writes `<basename>.pdf` into the outdir).
// A stored `output_rel` that points inside the output dir is honored when it
// clearly names a concrete file, so an agent that declares a non-default entry
// is respected.
export function artifactEntryPath(artifact) {
  const builder = artifact?.builder
  const outputRel = String(artifact?.output_rel ?? '')
  const marker = '/output/'
  const at = outputRel.indexOf(marker)
  const withinOutput = at !== -1 ? outputRel.slice(at + marker.length) : ''
  if (builder === 'latex') {
    if (withinOutput.toLowerCase().endsWith('.pdf')) return withinOutput
    const stem = fileStem(artifact?.source) || 'main'
    return `${stem}.pdf`
  }
  // website (and any unknown builder): a concrete output entry wins, else index.html.
  if (withinOutput && !withinOutput.endsWith('/')) return withinOutput
  return 'index.html'
}

// Whether the preview surface should hot-swap (reload the iframe / re-render the
// pdf) given the status BEFORE and AFTER a refresh. A finished build (building
// -> ok) is the swap trigger; a fresh `ok` first seen (no prior status, e.g. the
// tab opened after the build finished) also loads once. Same status, or a
// transition into building/error, never swaps.
export function shouldHotSwapPreview(prevStatus, nextStatus) {
  if (nextStatus !== 'ok') return false
  if (prevStatus === 'ok') return false
  return true
}

// A build-status system event addressed at THIS project. The backend event
// shape is coordinated via the build spec's event section; this reads it
// leniently (any of the plausible id field names) so a small naming difference
// on the backend does not silently drop live updates.
export function isArtifactBuildEvent(ev) {
  if (!ev || typeof ev !== 'object') return false
  return ev.type === 'artifact_build_status'
    || ev.type === 'project_artifact_build'
    || ev.type === 'artifact_build'
}

export function buildEventProjectId(ev) {
  const raw = ev?.projectId ?? ev?.project_id ?? null
  return raw == null ? null : String(raw)
}

export function buildEventArtifactId(ev) {
  const raw = ev?.artifactId ?? ev?.artifact_id ?? null
  return raw == null ? null : String(raw)
}
