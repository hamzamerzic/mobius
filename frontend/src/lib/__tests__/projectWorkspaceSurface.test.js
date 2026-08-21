import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const workspace = readFileSync(
  new URL('../../components/Projects/ProjectWorkspace.jsx', import.meta.url),
  'utf8',
)

test('the workspace keeps a New chat affordance in its chats strip', () => {
  assert.match(workspace, /void createChat\(\)/)
  assert.match(workspace, /Creating…[^]*New chat/)
})

test('the redesign composes the Finder + Artifacts zones and drops the build CTA', () => {
  assert.match(workspace, /<ProjectFinder\b/)
  assert.match(workspace, /<ProjectArtifacts\b/)
  // Artifacts replace the legacy /build/i template-action CTA.
  assert.doesNotMatch(workspace, /buildAction/)
  assert.doesNotMatch(workspace, /project-build-button/)
})
