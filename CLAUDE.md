# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Möbius is a self-hosted PWA where the owner chats with an AI agent to build mini-apps and modify the platform itself. The chat is the persistent control surface; a full-screen canvas renders whichever mini-app is active.

The "agent" is the Claude Code CLI running as a subprocess inside the Docker container. When the user sends a chat message, the backend spawns a `claude` process with the message, streams its output back via SSE, and saves the result. The agent can compile JSX into mini-apps, edit the shell UI, manage files, and run scheduled tasks.

The whole platform runs in a single Docker container and is installable on Android/iOS as a PWA.

## Commands

### Build and test (Docker — recommended)

```bash
cp .env.example .env   # fill in DOMAIN and SECRET_KEY
docker compose up -d --build
docker compose logs -f
```

`SECRET_KEY` must be at least 32 characters. Generate one with `python3 -c "import secrets; print(secrets.token_hex(32))"`. If not set, the entrypoint auto-generates one and persists it to `/data/.secret-key`.

Rebuild after changes with `docker compose up -d --build`. The Docker image bundles everything the agent needs (Claude CLI, esbuild, Node) so the full platform works out of the box.

### Agent refresh

Resetting the agent's runtime state back to a clean baseline while preserving all user data (chats, mini-apps, DB). Do this when the agent has accumulated UI drift, or to pick up upstream shell changes after a deploy.

1. Read `/data/shared/agent-experience.md` and `/data/logs/chat.log` for anything worth upstreaming to `backend/scripts/seed-agent-experience.md`.
2. Add non-instance-specific discoveries to the seed file and commit/deploy.
3. Reset shell source: `docker exec mobius bash -c "cp -a /app/shell-src/. /data/shell/"`
4. Clear built output: `docker exec mobius rm -rf /data/shell/dist`
5. Rebuild: `docker exec mobius bash /app/scripts/rebuild_shell.sh`
6. Reset experience file: `docker exec mobius cp /app/scripts/seed-agent-experience.md /data/shared/agent-experience.md`
   Then append instance-specific sections (apps built, per-instance gotchas) back in.

Chats, the SQLite DB, mini-app data, compiled JS, CLI auth credentials, and the theme are all untouched by this process.

## Architecture

```
Dockerfile (root)     Single-container image: frontend build + backend + CLI tools
docker-compose.yml    Self-hosted: Caddy (TLS) + app container
├── caddy             HTTPS reverse proxy — forwards everything to app:8000
└── app               FastAPI serves API + frontend static files
```

If adding to an existing Caddy setup, use `docker-compose.override.example.yml` to disable the bundled Caddy and join the existing Docker network.

### Frontend serving priority

At startup the server evaluates once:
```
/data/shell/dist/  ← preferred (agent's live rebuild, persists across deploys)
/app/static/       ← fallback (baked into image, always current with git HEAD)
```

If a change you deployed isn't showing up, `/data/shell/dist/` is overriding `/app/static/`. Either delete it and restart, or propagate changes through the agent's build with `rebuild_shell.sh`.

Never delete `/app/static/` — it's the only recovery fallback and is root-owned.

### Backend (`backend/app/`)

| File | Role |
|------|------|
| `main.py` | App factory: CORS, rate limiting, routers, static file serving |
| `config.py` | `Settings` via pydantic-settings; reads `.env` |
| `database.py` | SQLAlchemy engine, `SessionLocal`, `Base`, `get_db` |
| `models.py` | `Owner`, `App`, `Chat`, `PushSubscription`, `Notification` |
| `schemas.py` | Pydantic request/response models |
| `auth.py` | bcrypt hashing, JWT creation/decoding, Fernet encryption |
| `deps.py` | `get_current_owner` FastAPI dependency |
| `compiler.py` | Calls esbuild CLI to compile JSX string → ES module |
| `providers.py` | Pluggable CLI adapters (Claude Code); command building + event parsing |
| `broadcast.py` | `ChatBroadcast` per-chat event bus — decouples CLI subprocess from SSE |
| `chat.py` | `run_chat()` background task: spawns CLI, publishes events, saves to DB |
| `push.py` | VAPID key management and Web Push notification delivery |
| `theme.py` | Theme CSS management and HTML injection |
| `routes/auth.py` | Setup, login, CLI provider OAuth (`/api/auth/provider/*`) |
| `routes/apps.py` | CRUD for mini-app registry + module/frame serving |
| `routes/ai.py` | `POST /api/ai` — AI proxy for mini-apps |
| `routes/chat.py` | `POST /api/chat/stop` — stops agent subprocess |
| `routes/chats.py` | Chat CRUD + soft-delete with recovery |
| `routes/chats_stream.py` | `POST /messages` (starts agent, 202) + `GET /stream` (SSE) |
| `routes/generate.py` | Gemini image generation endpoint |
| `routes/notifications.py` | Push notification sending + history |
| `routes/notify.py` | System event notifications to active broadcasts |
| `routes/proxy.py` | Server-side CORS-bypass proxy for mini-apps |
| `routes/push.py` | Web Push subscription management |
| `routes/recover.py` | Recovery page at `/recover` — reset/backup/rebuild |
| `routes/recover_html.py` | HTML templates for recovery page |
| `routes/settings.py` | Owner-level configuration (API keys) |
| `routes/storage.py` | Per-app and shared file storage |
| `routes/uploads.py` | Per-chat file upload management |

### Frontend (`frontend/src/`)

Shell flow: `App.jsx` checks setup status → shows `SetupWizard` (first boot), `LoginForm` (no token), or `Shell` (authenticated).

`Shell` owns drawer state and system event handling. Navigation state and theme loading are extracted to hooks (`useNavigation`, `useTheme`).

| Component | Role |
|-----------|------|
| `Shell` | Logo bar, drawer, content area, system events |
| `Drawer` | Slide-in nav: current chat, new chat, collapsible history, apps |
| `ChatView` | Chat UI: message history, streaming, scroll management |
| `MsgContent` | Message rendering: markdown, tool blocks, attachments |
| `ToolBlock` | Collapsible tool execution block with status |
| `Attachments` | File/image attachment previews |
| `AppCanvas` | Sandboxed `<iframe>` for mini-apps |
| `SideNav` | Vertical navigation bar |
| `NavButton` | Dropdown navigation menu |
| `SettingsView` | Theme, API keys, provider auth |
| `SetupWizard` | First-boot: account + provider auth |
| `LoginForm` | Subsequent logins |
| `ProviderAuth` | Reusable Claude OAuth flow |
| `ConnectionStatus` | SSE reconnection indicator |
| `MenuButton` | Hamburger icon |

| Hook | Role |
|------|------|
| `useNavigation` | Navigation stack, pushState/popstate, Navigation API |
| `useTheme` | Theme CSS fetching, @import extraction, variable injection |
| `useStreamConnection` | SSE connection, text buffering, typewriter drain |
| `useVoiceInput` | Web Speech API with platform-specific workarounds |
| `useFileUpload` | File upload state and API calls |
| `usePushSubscription` | Web Push subscription after login |

| Markdown | Role |
|----------|------|
| `BlockRenderer` | Block-level token → React.memo component dispatch |
| `blocks` | Block component implementations (Paragraph, CodeBlock, Table, etc.) |
| `InlineContent` | Inline token rendering (text, bold, code, links, images) |
| `ImageLightbox` | Full-screen image viewer with pinch-zoom |
| `highlight` | Lazy-loaded highlight.js wrapper |
| `math` | KaTeX rendering wrapper |

### Mini-app contract

Every mini-app is a JSX file that esbuild compiles to an ES module. It must `export default` a React component receiving `{ appId, token }` props. The component calls `/api/storage/apps/{appId}/...` for persistence. See `skill/agent-skill.md` for the full contract.

### Data layout (`/data/` volume)

```
/data/
├── db/ultimate.db          SQLite database
├── compiled/app-*.js       esbuild output (one file per app)
├── apps/{id}/              per-app data files (written by mini-apps)
├── shared/                 cross-app shared files (theme.css, agent-experience.md)
├── shell/                  agent's editable shell copy (src/ + dist/)
├── cli-auth/claude/        CLI credentials (.credentials.json)
├── cron-logs/              output from scheduled task scripts
└── service-token.txt       long-lived JWT for cron scripts (chmod 600)
```

## Code style

- **Python**: 2-space indentation, 80-character line limit, Google-style docstrings.
- **Comments**: full sentences, no Title Case, no enumerated steps, no block annotations.
- **JS/JSX**: Vite defaults.

## Key env vars

| Var | Required | Purpose |
|-----|----------|---------|
| `SECRET_KEY` | Yes | Signs JWTs |
| `DOMAIN` | Yes (prod) | Domain Caddy gets a cert for; also sets `FRONTEND_ORIGIN` |
| `DATABASE_URL` | No | Defaults to `sqlite:////data/db/ultimate.db` |
| `DATA_DIR` | No | Defaults to `/data` |
| `FRONTEND_ORIGIN` | No | CORS allowed origin; defaults to `http://localhost:5173` |

## Auth

The owner's JWT (`auth.py:create_access_token`) lasts 30 days. On any 401 the frontend clears the token and reloads to login. This is a single-owner app — the long-lived token is appropriate.

CLI provider tokens are managed separately. The CLI's OAuth access token expires after a few hours, but the CLI auto-refreshes using the stored refresh token. If the refresh token itself expires, the user must re-authenticate via Settings > AI provider > Reconnect.

## CLI auth

No API keys are stored. Authentication uses self-managed PKCE OAuth (`routes/auth.py`) against Anthropic's token endpoint — the server generates PKCE params, the user authorizes in their browser, and the server exchanges the code for tokens.

The CLI's native headless auth (`claude auth login`) hangs indefinitely — it never reads the authorization code from piped stdin. This is why the self-managed PKCE flow exists.

Key details:
- Token endpoint: `https://platform.claude.com/v1/oauth/token`
- Token request body must be JSON, not form-urlencoded.
- The `state` parameter must be included in the token exchange.
- Credentials are written to `/data/cli-auth/claude/.credentials.json` in the CLI's expected format (`accessToken`, `refreshToken`, `expiresAt` in ms, `scopes` as array). The CLI auto-refreshes using `CLAUDE_CONFIG_DIR`.

## Version pinning

All key tool versions are pinned in the Dockerfile: `esbuild@0.20.2`, `@anthropic-ai/claude-code@2.1.92`, `python:3.12-slim`, `node:20-slim`.

The CLI is pinned because the PKCE OAuth workaround depends on internal constants (client_id, token URL, credential format) extracted from the CLI binary.

### Upgrade checklist (when bumping `@anthropic-ai/claude-code`)

1. Update the version in the Dockerfile.
2. Build and verify OAuth constants: `strings $(which claude) | grep -E 'oauth/token|client_id|credentials'`. Compare against `routes/auth.py`.
3. Test native headless auth: `echo '' | CLAUDE_CONFIG_DIR=/tmp/t claude auth login 2>&1`. If it hangs, the PKCE workaround is still needed.
4. Verify credential format unchanged: `accessToken`, `refreshToken`, `expiresAt` (ms), `scopes` (array) under a `claudeAiOauth` key.
5. End-to-end test: full auth flow + CLI chat.

## Development notes

### Streaming

The CLI sends `stream_event` with `content_block_delta` events containing `text_delta` for token-by-token streaming. The `--include-partial-messages` flag is required. `assistant` events are only used for `tool_use` blocks — don't use them for text.

### Broadcast and reconnection

The CLI subprocess publishes events to a `ChatBroadcast` (in-memory event bus). SSE clients subscribe via `GET /api/chats/{id}/stream` and receive a catch-up burst of all prior events, then live events. `POST /api/chats/{id}/messages` returns 202 and starts the agent as a background task.

The catch-up burst replays ALL events from the start of the response. Any reconnection path must reset `streamItems` before connecting — otherwise replayed events duplicate the initial response. When ChatView mounts and the agent is already running, it strips the partial assistant message from DB-loaded messages since the catch-up burst will replay it.

### Scroll positioning

A dynamic spacer below the message list ensures at least a viewport of space after the user's message. The formula:

```
spacer = max(0, viewH + scrollTarget − listEl.offsetHeight)
```

The spacer has three modes controlled by `needsSpacerRef` and `scrollTargetRef`:

1. **Send** (`needsSpacerRef=true`): computes `scrollTarget` from the last user message's `offsetTop`, scrolls to it, and starts a `ResizeObserver` to track content growth. While `spacer > 0` (content shorter than viewport), holds `scrollTop` at the user message. Once `spacer` hits 0 (content exceeds viewport), auto-follows new content if near the bottom.

2. **Promote/stop** (`needsSpacerRef=false`, `scrollTargetRef` set): recalculates spacer height once without touching scroll. Compensates for content height changes when thinking dots are removed or stream items are promoted to messages.

3. **Mount/history** (`scrollTargetRef=null`): does nothing. Spacer height is restored from `sessionStorage` alongside scroll position.

Key rules:
- **Use current `viewH`, not a cached max.** `interactive-widget=resizes-content` in the viewport meta tag makes Android resize the layout viewport when the keyboard opens. The spacer must track this.
- **Measure `listEl.offsetHeight`, not `scrollEl.scrollHeight`.** A scroll container's `scrollHeight` never goes below `clientHeight`, producing wrong values when content is short.
- **No React `style` prop on the spacer.** Direct DOM manipulation via ref — React re-applies style props on every render, fighting the spacer updates.
- **`spacerActive` keeps `min-height: 0` on the list** while the spacer is active. Without this, `min-height: calc(100% + 1px)` inflates `offsetHeight` and breaks the formula.
- **`lastUserMsgRef` via `lastUserIdx`** — assigning the same ref to multiple list elements is unreliable (React doesn't re-assign refs on existing elements).
- **Spacer height is persisted** in `sessionStorage` alongside scroll position (`_spacerHeights`). Both are restored together on mount so the scroll math stays consistent.
- `.chat__scroll` must have `position: relative` (for `offsetTop`). `.spacer-dynamic` must NOT have a CSS transition. Don't add `visualViewport` resize listeners — they fire on keyboard open/close and conflict with `interactive-widget`.

### Scroll restoration

Scroll position is saved as distance-from-bottom (`scrollHeight - scrollTop`) on every scroll event in `_scrollPositions[chatId]`. Spacer height is saved alongside it in `_spacerHeights[chatId]`. Both are persisted to `sessionStorage` on unmount.

On mount, the spacer is restored first (it affects `scrollHeight`), then `scrollTop = scrollHeight - saved`. A delayed re-apply (300ms) corrects drift from lazy renderers — KaTeX math, syntax highlighting, and table styling load async and change content height after the initial restore.

**Do not hide/fade the scroll area during restoration.** Attempts to suppress reflow jitter with `visibility: hidden` or `opacity: 0` cause a visible flash that's worse than the jitter itself, because `useLayoutEffect` fires after React commits DOM mutations but the browser may have already painted the previous frame.

### Android keyboard

The viewport meta tag includes `interactive-widget=resizes-content`, which makes Android Chrome resize the layout viewport (not just the visual viewport) when the keyboard opens. This is required so `position: fixed` elements (the shell, input bar) reflow correctly. Without it, the browser scrolls the page to keep the focused input visible, pushing the toolbar off screen.

The spacer uses current `viewH` (not a cached max) because the viewport legitimately shrinks when the keyboard opens. A cached `maxViewH` would size the spacer for the full viewport even with the keyboard open, causing the scroll target to land at the wrong position on subsequent sends.

### Streaming rendering

Block-memoized markdown renderer: `marked.lexer()` tokenizes into blocks, each rendered as a `React.memo()` component. Only the last (active) block re-renders as tokens arrive. Text tokens are buffered and drained via `requestAnimationFrame` for a typewriter effect (~3 chars/frame at 60fps). Don't replace this with streaming-markdown or innerHTML approaches — they lose control over individual element types.

### Voice input

Uses `SpeechRecognition` with `continuous: false` and `interimResults: true`. Sessions auto-stop after silence; `onend` restarts with a new instance.

Don't use `continuous: true` — it's broken on Android Chrome (results array grows indefinitely, duplicate events). Filter `confidence === 0` finals — Android Chrome fires duplicates. The `onChange` guard (`if (listeningRef.current) return`) blocks Chrome's OS dictation layer from racing with `onresult`.

### Session isolation

Each chat stores a `session_id` from the CLI. First message starts a fresh session; subsequent messages use `--resume {session_id}`. This prevents cross-chat context leakage.

### System prompt

The skill (`skill/agent-skill.md`) is passed as `--system-prompt-file` only on the first message. Resumed sessions inherit the system prompt from creation — start a fresh chat after deploying skill changes.

Dynamic per-session data (experience file, timezone) is injected into the first user message as an `<agent_context>` block, not the system prompt. Static content goes first for prompt cache efficiency.

### Agent write access

The agent (mobius user) can only write to `/data/`. Backend code, static files, and shell-src are root-owned. `protected-files.txt` lists credential-handling components that the entrypoint locks to chmod 444.

### Skill/experience split

- `skill/agent-skill.md` — what the agent can do. Checked into git. Deploys to new chats immediately.
- `/data/shared/agent-experience.md` — what the agent has learned through use. Lives on the volume. Never overwritten by deploys.
- `backend/scripts/seed-agent-experience.md` — seed file applied on first boot only.

### Scheduled agents

The container has `cron` installed. A long-lived service token at `/data/service-token.txt` (chmod 600) enables cron scripts to invoke the `claude` CLI with `--system-prompt-file` for AI-powered scheduled tasks.

### PWA icons

Icons (192, 512, apple-touch-icon) have a solid background matching `--bg`. When the theme's `--bg` changes, icons must be regenerated (1.25x padding for Android maskable safe zone). The server injects `--bg` into the manifest's colors dynamically, but icon PNGs are static.

### Elastic overscroll

`.chat__scroll` uses `overscroll-behavior-y: contain` and `transform: translateZ(0)`. `.chat__list` has `min-height: calc(100% + 1px)` — required for iOS Safari elastic bounce at scroll bottom.
