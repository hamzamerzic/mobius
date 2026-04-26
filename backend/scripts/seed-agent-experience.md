# Experience

## About this file

This is the agent's memory across sessions. It's a real file at
`/data/shared/agent-experience.md`. The block you're reading now is
a snapshot taken at the start of this session; another session may
have edited the real file since.

**To append** (the common case — new app, gotcha, preference):

```bash
echo '- Built **Name** (id N). <one-line description>' >> /data/shared/agent-experience.md
```

Use `Bash >>` — it bypasses the Read-before-modify constraint that
`Edit` and `Write` have.

**To read the latest** mid-session: `Read` the path above.

**To delete an outdated entry**: `Read` the file, then `Edit` to
remove the stale line.

**Rules:**
- New entries go at the bottom.
- If newer entries conflict with older ones, the newer entry is
  correct — trust recent information over stale.
- If an entry is outdated or irrelevant, delete it. Stale entries
  mislead future sessions.
- Update in the SAME turn as the action, before writing the final
  assistant message.

**What goes in your /data/shared/agent-experience.md (this file):**
- A new app was built → `- Built **Name** (id N). <description>`
- A gotcha or workaround discovered → a one-liner
- A partner preference learned → a one-liner
- Shell / CSS / cron changed → what and why

**What goes in `backend/scripts/seed-agent-experience.md` (the seed
that ships to other Möbius users on first boot)** is a stricter
filter — that file is the kickstart for fresh installs, NOT a
knowledge dump of one user's app history. The bar for adding
something there:

> **Frequency × cost test.** If most agents would re-discover this
> within a single build of an unrelated app, AND the discovery
> costs more than a couple of tool calls, AND the friction would
> be paid on most builds — seed it. Otherwise don't. A fix
> specific to one library/visual quirk that only matters when
> building one kind of app belongs in the running experience
> file, not the seed.

In other words: prefer seeding **platform contracts the agent
cannot read off the codebase** (storage API shape, register_app.py
preference, scoped-token gotcha, theme-reset path) and **patterns
that pay off on every build** (mobile-first, CSS variables, mini-
app contract). Don't seed library-specific shader tricks, niche
canvas-pointer quirks, or anything that the agent will only need
when building exactly the kind of app the previous agent built.

**After updating**, tell the partner what you wrote and why — not
just that you updated it. They can't see your tool calls.

**Before writing your final message**, scan the session for any
infrastructure discoveries, wrong assumptions, or workarounds you
hit along the way. Each one is a gotcha worth logging — future
sessions will thank you.

## Experience log

Add new entries at the bottom. Delete outdated ones. No timestamps;
order is implicit.

- Built **Hello World**. A welcome screen with an "ask the agent"
  button that takes the user to chat. The simplest possible starting
  point — proves the app contract works and gives the user somewhere
  to click.

## Mini-app contract (everything you need; do NOT read app-frame.html)

A mini-app is a single JSX file whose default export is a React
component receiving `{ appId, token }` props. The platform compiles
it via esbuild and renders it in a sandboxed iframe.

```jsx
export default function MyApp({ appId, token }) {
  // ... your UI
  return <div>...</div>
}
```

**Available imports** (already in the import map — no install needed):
`react`, `react/jsx-runtime`, `react-dom`, `react-dom/client`,
`recharts`, `date-fns`, `three`, `three/addons/*`. Anything else
loads via dynamic `import()` from esm.sh.

**Storage API** (per-app key/value file storage):

```js
// read
fetch(`/api/storage/apps/${appId}/file.json`, {
  headers: { Authorization: `Bearer ${token}` }
}).then(r => r.ok ? r.json() : null)

// write
fetch(`/api/storage/apps/${appId}/file.json`, {
  method: 'PUT',
  headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ content: JSON.stringify(myData) })
})

// delete
fetch(`/api/storage/apps/${appId}/file.json`, {
  method: 'DELETE',
  headers: { Authorization: `Bearer ${token}` }
})
```

A 404 on first read is normal — handle with a default value.

**External fetches** go through `/api/proxy?url=<urlencoded>`:

```js
const url = `/api/proxy?url=${encodeURIComponent(externalUrl)}`
fetch(url, { headers: { Authorization: `Bearer ${token}` } })
```

**Register / update**: use `python "$SCRIPTS_DIR/register_app.py" "<name>" "<description>" apps/<name>/index.jsx`
— it handles compile + DB write + on-disk source in one call.

## Shell structure

| File | Controls |
|------|---------|
| `Shell/Shell.jsx` | Logo bar, drawer toggle, layout, system events |
| `Shell/Shell.css` | Logo bar and layout styles |
| `ChatView/ChatView.jsx` | Chat messages, streaming, scroll |
| `ChatView/ChatView.css` | Chat styles |
| `ChatView/ChatInput.jsx` | Chat input, voice, file upload, send/stop |
| `ChatView/ChatInput.css` | Input styles |
| `Drawer/Drawer.jsx` | Side drawer, chat list, app list |
| `Drawer/Drawer.css` | Drawer styles |
| `AppCanvas/AppCanvas.jsx` | Mini-app iframe |
| `index.css` | Global CSS variables and resets |

## Design principles

- CSS variables (`var(--bg)`, `var(--accent)`, etc.) — never hardcode colors
- Check `/data/shared/theme-mode` to know light vs dark mode
- Typography: choose fonts that match the mood, Google Fonts via `@import`
- Color: cohesive palette using the existing CSS variables as a base
- Motion: subtle CSS transitions for hover and state changes
- Spatial: generous negative space, consistent padding
- Mobile-first: the partner's viewport size is in the session context

## Shell change costs

- **theme.css only (no rebuild):** color variables, gradients, background
  images, `@keyframe` animations, Google Fonts via `@import`, CSS filters,
  pseudo-elements on stable class names, `backdrop-filter`. Hot-reloaded instantly.
- **app-frame.html (no rebuild):** `/data/shell/public/app-frame.html` is
  read per-request by the backend, not compiled. Edit it directly to add
  libraries to the import map or change the mini-app runtime.
- **JSX/CSS edit + rebuild:** new DOM elements, React-managed animations,
  canvas, particle systems, structural layout changes.
  Each rebuild triggers a visible page transition — batch all edits before rebuilding.

## Gotchas

- **Reverting the theme:** `DELETE /api/storage/shared/theme.css` (no
  body needed). The platform owns defaults — `/api/theme` returns the
  user override if present, otherwise the built-in default. Don't try
  to write a "minimal" theme.css with only a few variables; it gets
  shadowed by the server-injected initial-render block. Either
  override completely OR delete entirely.
- Cron + storage API can get out of sync. Either have cron read from the
  storage API via curl, or have the UI write to the filesystem too.
- Cron scripts need `CLAUDE_CONFIG_DIR=/data/cli-auth/claude`.
- `|` inside `$...$` in markdown tables breaks both. Use `\mid` or `\vert`.
- Mini-apps get a scoped token, not the owner's full JWT. It can access
  storage, proxy, AI, notifications, push — but NOT auth, settings, or chat.
- Storage 404 on first load is normal — handle with default value.
- Back gesture in apps: use `pushState`/`popstate` for internal navigation.
- Async assets (Three.js textures, images, lazy components, fonts)
  aren't rendered at the moment `agent-browser open` returns —
  screenshots captured immediately come back empty or half-loaded.
  Wait for them: `agent-browser open "$URL" && agent-browser wait <ms> && agent-browser screenshot "$OUT"`.
  **Scale the wait to the heaviest asset** — Three.js textures /
  WebGL / large fonts → 6000–8000ms; ordinary React apps with local
  state → 1000–1500ms; static HTML → 200ms. Blanket-8000 everywhere
  wastes session time.
- Proxy endpoint is `/api/proxy?url=<urlencoded>` — the external URL
  MUST be URL-encoded. Building the call inline:
  `curl -s "$API_BASE_URL/api/proxy?url=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=""))' "https://example.com/api")"`.
  Raw unencoded URLs will be routed wrong or rejected.
- **Mini-apps must forward their scoped token on proxy calls.** The
  iframe passes `token` as a prop to the default-exported component.
  Inside the app, include it on every proxy request:
  `fetch(\`/api/proxy?url=\${encodeURIComponent(url)}\`, {
    headers: { Authorization: \`Bearer \${token}\` }
  })`. Without the header the proxy returns silently empty data and
  the app looks broken for no visible reason.
- Three.js: `import * as THREE from 'three'` and
  `import { OrbitControls } from 'three/addons/controls/OrbitControls.js'`
  just work (self-hosted at `/vendor/three/` via the app-frame
  import map — no esm.sh waterfall).

## Debug endpoints

- Active agents: `curl -s -H "Authorization: Bearer $AGENT_TOKEN" "$API_BASE_URL/api/debug/status"`
- Chat logs: `curl -s -H "Authorization: Bearer $AGENT_TOKEN" "$API_BASE_URL/api/debug/logs?lines=50"`
- Filter by chat: add `&chat_id=<id>` to the logs endpoint.

## Screenshots and interactive testing with agent-browser

`agent-browser` is a CLI for a headless Chromium, installed globally
in the container. Session-based: open a URL once, then take screenshots,
click, fill, etc. against that session.

### Basic screenshot

```bash
APP_ID=<id>
APP_URL="$API_BASE_URL/api/apps/$APP_ID/frame?token=$AGENT_TOKEN&v=$(date +%s)"
OUT="/data/chats/$CHAT_ID/generated/app-$APP_ID-preview.png"
mkdir -p "$(dirname "$OUT")"

# Viewport W and H come from the `Viewport: WxH` line in the session
# context above. Substitute those exact values — do NOT invent a default.
agent-browser set viewport <W> <H>
agent-browser open "$APP_URL"
agent-browser screenshot "$OUT"
agent-browser close
```

- The partner's viewport is in the session context as `Viewport: WxH`.
  If that line is missing, ask the partner instead of guessing — a
  wrong viewport silently produces misleading screenshots.
- Embed the PNG inline in the next chat message:
  `![preview](/api/chats/<chat_id>/generated/app-<id>-preview.png)`

### Interactive testing

The session stays open between commands until `close` is called, so
interactions (click, fill, drag, scroll) can be sequenced.

```bash
agent-browser set viewport <W> <H>    # from `Viewport: WxH` in context
agent-browser open "$APP_URL"
agent-browser snapshot                     # elements with @eN refs (text)
agent-browser click @e5                    # click "Add Task"
agent-browser fill @e8 "Buy groceries"     # clear + type into a field
agent-browser press Enter                  # submit
agent-browser screenshot /data/chats/$CHAT_ID/generated/after-click.png
agent-browser close
```

Common commands: `click <sel>`, `fill <sel> <text>`, `type <sel> <text>`,
`press <key>`, `drag <src> <dst>`, `scroll <dir>`, `wait <sel|ms>`,
`get text <sel>`, `eval <js>`.

Use interactive testing to verify interactions (drag-and-drop,
form submission, navigation) before claiming an app is done.

## Notifications

```bash
curl -s -X POST -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"App ready","body":"<name> is built and ready to use"}' \
  "$API_BASE_URL/api/notifications/send"
```

Send a notification after finishing or updating an app so the partner
knows even if they've switched tabs.
