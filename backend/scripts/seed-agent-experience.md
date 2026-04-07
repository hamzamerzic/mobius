# Agent experience

Accumulated knowledge from working in this Möbius instance. Read at the
start of every session. Update when you learn something future sessions
should know. Keep it concise — this is injected into every session prompt.

## Apps built

| ID | Name | Description |
|----|------|-------------|
| 1  | Hello World | Starter app — welcome screen with "ask the agent" button |

## Platform state

- Shell source: `/data/shell/src/` — editable JSX/CSS/components
- Shell build: `/data/shell/dist/` — Vite output, overrides `/app/static/`
- Read-only originals: `/app/shell-src/`
- Rebuild command: `bash /app/scripts/rebuild_shell.sh`
- Theme (CSS-only, no rebuild): `/data/shared/theme.css`
- Theme mode (`"light"` or `"dark"`): `/data/shared/theme-mode`
- Notify after theme change: `bash "$SCRIPTS_DIR/notify_theme.sh"`

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

## Stable CSS class names for theme targeting

`.sidenav`, `.sidenav__item`, `.drawer`, `.drawer__item`, `.chat__text`,
`.chat__text--user`, `.chat__text--assistant`, `.chat__form`, `.chat__input`,
`.md-blocks`, `.md-paragraph`, `.md-code-block`, `.md-heading`.

## Listing existing apps

```bash
curl -s -H "Authorization: Bearer $AGENT_TOKEN" "$API_BASE_URL/api/apps/" | python3 -m json.tool
```

Check this before building something that might already exist.

## Design principles

- Use CSS variables (`var(--bg)`, `var(--accent)`, etc.) — never hardcode colors
- Check `/data/shared/theme-mode` to know light vs dark mode
- Typography: choose fonts that match the mood, use Google Fonts via @import
- Color: cohesive palette using the existing CSS variables as a base
- Motion: subtle CSS transitions for hover and state changes
- Spatial: generous negative space, consistent padding

## Reusable components for mini-apps

The shell includes components that mini-apps can reference as patterns:

| Component | Path | Purpose |
|-----------|------|---------|
| `ChatInput` | `ChatView/ChatInput.jsx` | Text input with voice, file attach, send/stop |
| `BlockRenderer` | `ChatView/markdown/BlockRenderer.jsx` | Streaming markdown renderer |
| `InlineContent` | `ChatView/markdown/InlineContent.jsx` | Inline markdown (links, images, math) |
| `ImageLightbox` | `ChatView/markdown/ImageLightbox.jsx` | Pinch-zoom image viewer |

Mini-apps can't import these directly (different bundle) but use them as
reference implementations.

## Shell change costs

- **theme.css only (no rebuild):** color variables, gradients, background
  images, `@keyframe` animations, Google Fonts via `@import`, CSS filters,
  pseudo-elements on stable class names, `backdrop-filter`. Hot-reloaded instantly.
- **JSX/CSS edit + rebuild:** new DOM elements, React-managed animations,
  canvas, particle systems, structural layout changes.
  Each rebuild triggers a visible page transition — batch all edits before rebuilding.

## User preferences

(none yet — update as you learn them)

## Known gotchas

- When an app has both a cron script (reads from filesystem) and a UI
  settings tab (reads/writes via storage API), the two can get out of
  sync. Either have the cron script read from the storage API via curl,
  or have the UI write to the filesystem path too.
- Cron scripts that call the `claude` CLI must set
  `CLAUDE_CONFIG_DIR=/data/cli-auth/claude` — cron runs in a clean environment
  and won't find credentials at the default `~/.claude/` path.
- **Math inside markdown tables:** the chat renders markdown first, then
  KaTeX. A `|` inside `$...$` in a table cell gets interpreted as a
  column separator before KaTeX sees it, breaking both the table and the
  math. Use `\mid` (conditionals) or `\vert` (norms) instead of `|`
  when writing math inside table cells.
- Mini-apps receive a scoped token, not the owner's full JWT. The scoped
  token can access storage, proxy, AI, notifications, and push — but NOT
  auth, settings, or chat endpoints.
- **PWA icon regeneration**: when changing `--bg` in theme.css, icons
  (192, 512, apple-touch-icon) embed the background color and need
  regenerating. See the skill file for the recipe.
