import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  artifactEntryPath,
  artifactStatus,
  artifactStatusPill,
  buildEventArtifactId,
  buildEventProjectId,
  isArtifactBuildEvent,
  isBuilding,
  normalizeArtifacts,
  shouldHotSwapPreview,
} from '../projectArtifacts.js'

test('normalizeArtifacts reads a bare array or an envelope, and drops malformed rows', () => {
  assert.deepEqual(normalizeArtifacts([{ id: 'a' }, { id: 'b' }]).map(r => r.id), ['a', 'b'])
  assert.deepEqual(normalizeArtifacts({ artifacts: [{ id: 'a' }] }).map(r => r.id), ['a'])
  // Lenient read: a hand-edited manifest with junk entries never throws.
  assert.deepEqual(normalizeArtifacts([{ id: 'a' }, null, {}, { id: '' }, 'x']).map(r => r.id), ['a'])
  assert.deepEqual(normalizeArtifacts(undefined), [])
})

test('artifactStatus and pill map the four states, unknown reads as idle', () => {
  assert.equal(artifactStatus({ status: 'building' }), 'building')
  assert.equal(artifactStatus({ status: 'nonsense' }), 'idle')
  assert.equal(artifactStatus(null), 'idle')
  assert.equal(artifactStatusPill({ status: 'ok' }).variant, 'ok')
  assert.equal(artifactStatusPill({ status: 'error' }).variant, 'error')
  assert.equal(isBuilding({ status: 'building' }), true)
  assert.equal(isBuilding({ status: 'ok' }), false)
})

test('artifactEntryPath: website entry is index.html unless a concrete output is declared', () => {
  assert.equal(artifactEntryPath({ builder: 'website' }), 'index.html')
  assert.equal(
    artifactEntryPath({ builder: 'website', output_rel: 'artifacts/site/output/index.html' }),
    'index.html',
  )
  assert.equal(
    artifactEntryPath({ builder: 'website', output_rel: 'artifacts/site/output/home.html' }),
    'home.html',
  )
})

test('artifactEntryPath: latex resolves the compiled pdf from source or output_rel', () => {
  assert.equal(artifactEntryPath({ builder: 'latex', source: 'main.tex' }), 'main.pdf')
  assert.equal(artifactEntryPath({ builder: 'latex', source: 'paper/thesis.tex' }), 'thesis.pdf')
  assert.equal(
    artifactEntryPath({ builder: 'latex', source: 'main.tex', output_rel: 'artifacts/x/output/report.pdf' }),
    'report.pdf',
  )
})

test('shouldHotSwapPreview fires only when a build reaches ok freshly', () => {
  assert.equal(shouldHotSwapPreview('building', 'ok'), true) // build finished
  assert.equal(shouldHotSwapPreview('', 'ok'), true)         // tab opened after a build
  assert.equal(shouldHotSwapPreview('idle', 'ok'), true)
  assert.equal(shouldHotSwapPreview('ok', 'ok'), false)       // already showing this build
  assert.equal(shouldHotSwapPreview('idle', 'building'), false)
  assert.equal(shouldHotSwapPreview('building', 'error'), false)
})

test('build-status event detection reads plausible id field names leniently', () => {
  assert.equal(isArtifactBuildEvent({ type: 'artifact_build_status' }), true)
  assert.equal(isArtifactBuildEvent({ type: 'project_artifact_build' }), true)
  assert.equal(isArtifactBuildEvent({ type: 'app_updated' }), false)
  assert.equal(buildEventProjectId({ projectId: 5 }), '5')
  assert.equal(buildEventProjectId({ project_id: '9' }), '9')
  assert.equal(buildEventProjectId({}), null)
  assert.equal(buildEventArtifactId({ artifactId: 'site' }), 'site')
  assert.equal(buildEventArtifactId({ artifact_id: 'doc' }), 'doc')
})
