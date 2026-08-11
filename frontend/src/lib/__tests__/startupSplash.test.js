import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const frontend = join(here, '..', '..', '..')
const src = join(frontend, 'src')
const app = readFileSync(join(src, 'App.jsx'), 'utf8')
const shell = readFileSync(join(src, 'components', 'Shell', 'Shell.jsx'), 'utf8')
const index = readFileSync(join(frontend, 'index.html'), 'utf8')

test('authenticated launch cover waits for the shell first frame', () => {
  const staticBoot = index.slice(
    index.indexOf('var isChatEmbed'),
    index.indexOf("// Prevent browser from scrolling to top on refresh."),
  )
  assert.match(staticBoot, /if \(isChatEmbed\) \{[\s\S]*?s\.remove\(\)/,
    'only the inert embed may remove the cover before React starts')
  assert.doesNotMatch(staticBoot, /isChatEmbed \|\| hasOwnerToken/,
    'an owner token alone is not visual readiness')

  assert.match(app,
    /const \[shellVisualReady, setShellVisualReady\] = useState\(false\)[\s\S]*?const markShellVisualReady = useCallback/,
    'App must wait for a shell-owned visual readiness signal')
  assert.match(app,
    /if \(!hasToken \|\| status !== 'shell' \|\| isRestoring\) return[\s\S]*?STANDALONE_APP \|\| shellVisualReady \|\| showingDegradedNotice[\s\S]*?removeSplash\(\)/,
    'restored authenticated shells keep the cover until a safe visible surface exists')
  assert.match(app, /<Shell onInitialVisualReady=\{markShellVisualReady\} \/>/)

  assert.match(shell,
    /PaneChatView calls this after the destination's display-ready frame has[\s\S]*?markInitialVisualReady\(\)/,
    'a real chat releases the cover only after its own stable frame')
  assert.match(shell,
    /if \(activeView === 'chat' && activeChatId\) return undefined/,
    'the generic fallback must not pre-empt a concrete chat restoration')
})
