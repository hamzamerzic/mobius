import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const workspace = readFileSync(
  new URL('../../components/Projects/ProjectWorkspace.jsx', import.meta.url),
  'utf8',
)

test('project add menu can create another chat from any folder', () => {
  assert.match(workspace, /role="menuitem"[^]*?void createChat\(\)/)
  assert.match(workspace, /Creating chat…[^]*New chat/)
})

test('compact artifact build control keeps its action name', () => {
  assert.match(workspace, /className="project-build-button"[^>]+aria-label=\{buildAction\.name \|\| 'Build'\}/)
  assert.match(workspace, /title=\{buildAction\.name \|\| 'Build'\}/)
})
