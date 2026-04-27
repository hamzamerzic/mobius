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
| `routes/debug.py` | Observability: active procs, broadcasts, chat logs |

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

### Mini-app sandbox — accepted same-origin decision

`AppCanvas.jsx` mounts the mini-app iframe with
`sandbox="allow-scripts allow-same-origin"`. The combination grants
the mini-app's JS DOM access to the parent shell — including the
owner JWT in `localStorage` — and is flagged as risky by generic
audits.

**This is an accepted trade-off, not a bug.** Möbius is a single-
owner PWA where every mini-app is authored by the owner's own agent
(Claude Code CLI running with the owner's credentials). The threat
model treats the agent and the owner as the same trust principal:
if the agent is compromised, it already has shell write access and
can edit the platform itself. Sandboxing the iframe more strictly
buys nothing against that adversary, while same-origin gives the
agent's apps simple `fetch('/api/...')` calls and access to the
font/CSS shell environment.

Removing `allow-same-origin` would require relocating mini-apps to
a separate origin (a subdomain like `apps.<DOMAIN>`, or `srcdoc=` /
`data:` URIs). That's a non-trivial refactor — service-worker scope,
import maps, the `/api/apps/{id}/module` route, the storage API
auth, and the Caddy config all need to change in lockstep — and it's
only worth doing if the threat model changes (e.g. multi-tenant
deployments, third-party app marketplace, untrusted-author apps).

**Re-evaluate when:** Möbius gains multiple owners on one instance,
mini-apps come from sources other than the owner's own agent, or the
agent's CLI runs with reduced trust relative to the owner.

### Data layout (`/data/` volume)

```
/data/
├── db/ultimate.db          SQLite database
├── compiled/app-*.js       esbuild output (one file per app, keyed by numeric id)
├── apps/<slug>/index.jsx   agent-editable JSX source (keyed by app name slug)
├── apps/<slug>/...         per-app data files written by the mini-app at runtime
├── shared/                 cross-app shared files (theme.css, agent-experience.md)
├── shell/                  agent's editable shell copy (src/ + dist/)
├── cli-auth/claude/        CLI credentials (.credentials.json)
├── cron-logs/              output from scheduled task scripts
└── service-token.txt       long-lived JWT for cron scripts (chmod 600)
```

### Copying apps between instances

`POST /api/apps/` (with `jsx_source` in the body) stores the source
in the DB and writes the compiled bundle to `/data/compiled/app-N.js`
— but it does NOT write `/data/apps/<slug>/index.jsx`. Without that
on-disk source, the destination agent can't find and edit the app
later; it would have to recreate it from scratch. Also note that
`GET /api/apps/{id}` does not return `jsx_source` (the `AppOut`
schema omits it) so the source is not retrievable via API once
shipped.

**When copying an app to another instance, ship both:**

```bash
# 1. POST the source → DB + compiled bundle
docker exec <dst> curl -s -X POST \
  -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" \
  -d "$(python3 -c 'import json,sys;print(json.dumps({"name":"X","description":"...","jsx_source":open(sys.argv[1]).read()}))' /tmp/src.jsx)" \
  http://localhost:8000/api/apps/

# 2. Copy the source tree so the agent can edit in place later
docker exec <src> cat /data/apps/<slug>/index.jsx > /tmp/src.jsx
docker exec <dst> mkdir -p /data/apps/<slug>
docker cp /tmp/src.jsx <dst>:/data/apps/<slug>/index.jsx
docker exec <dst> chown -R mobius:mobius /data/apps/<slug>
```

Direct `docker cp` between containers is not supported — always
stage through the host filesystem in `/tmp/`.

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

All key tool versions are pinned in the Dockerfile: `esbuild@0.20.2`, `@anthropic-ai/claude-code@2.1.112`, `agent-browser` (unpinned, downloads its own Chromium), `python:3.12-slim`, `node:20-slim`.

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

### Chat UX — non-negotiable constraints

These behaviors are load-bearing. Any change to scroll, spacer, keyboard,
or rendering code must preserve all of them.

1. **Spacer on send.** When the user sends a message, a dynamic spacer is
   added below the message list so the user's message scrolls to the top
   of the viewport. The spacer height is set *before* `scrollTop`.

2. **No scroll fighting.** The ResizeObserver updates spacer height as
   content streams in. It sets `scrollTop` in two cases: (a) content
   shrank and the browser clamped scrollTop below `scrollTarget`
   (clamp-fix), (b) auto-follow — if the user is "near the bottom",
   snap to bottom so content growth doesn't leave them behind.
   Auto-follow starts **OFF** after every send — the user sees their
   message at the top and the response growing below it, like a
   terminal. Auto-follow only engages when the user actively scrolls
   to within 50px of the bottom. "Near the bottom" (`gap < 50`) is
   tracked by a passive scroll listener on `.chat__scroll`. This
   avoids yanking the user away from what they're reading — they
   scroll down when ready.

3. **Re-anchor on promote.** When streaming ends and items are promoted
   to messages, the content structure changes. The spacer is recalculated
   and `scrollTop` is re-set to `scrollTarget` to prevent layout shift.

4. **fullViewH for spacer sizing.** The spacer uses `fullViewHRef` — the
   keyboard-closed viewport height captured once on mount. This prevents
   the keyboard open/close cycle from changing `scrollHeight` and causing
   scroll position resets. Do NOT use current `clientHeight` for the
   spacer formula.

5. **overflow-anchor: none.** Chrome's scroll anchoring fights the spacer.
   Disabled on `.chat__scroll`.

6. **Keyboard handling.** `interactive-widget=resizes-content` is used.
   The `.chat__scroll` container mounts on the first user send and
   stays mounted for the rest of the session — empty chats render a
   standalone `.chat__empty-wrap` sibling instead. The shift-prevention
   the scroll container provides is only needed once there's a message
   list to anchor, so the empty state is exempt. On non-PWA Android
   browser, opening the keyboard causes a small visual shift (~3px)
   once the scroll container is mounted — this is native browser
   behavior and cannot be prevented without removing `resizes-content`.

7. **Scroll position is saved.** On every scroll event, position is saved
   as `scrollHeight − scrollTop` in `_scrollPositions[chatId]`. Spacer
   height is saved alongside in `_spacerHeights[chatId]`. Both persist to
   `sessionStorage` on unmount. On mount, spacer is restored first, then
   `scrollTop = scrollHeight − saved`. A 300ms re-apply corrects drift
   from lazy renderers (highlight.js).

8. **Streaming renders without jitter.** Block-memoized markdown: only
   the last (active) block re-renders as tokens arrive.

### Spacer implementation

Formula: `spacer = max(0, fullViewH + scrollTarget − listEl.offsetHeight)`

Two modes controlled by `needsSpacerRef` and `scrollTargetRef`:

1. **Send** (`needsSpacerRef=true`): computes `scrollTarget` from the
   last user message's `offsetTop`, sets spacer height, sets `scrollTop`,
   starts a `ResizeObserver` to track content growth.

2. **Promote/stop** (`isSend=false`, `scrollTargetRef` set): recalculates
   spacer and re-anchors `scrollTop` to `scrollTarget`.

Key rules:
- **Set spacer height before `scrollTop`.** Otherwise the browser clamps.
- **Use `fullViewHRef`**, not current `clientHeight`. Set once on mount.
- **Measure `listEl.offsetHeight`**, not `scrollEl.scrollHeight`.
- **No React `style` prop on the spacer.** Direct DOM manipulation via ref.
- **`spacerActive` keeps `min-height: 0` on the list** while active.
- **`lastUserMsgRef` via `lastUserIdx`** — one ref, one element.
- `.chat__scroll` must have `position: relative` and `overflow-anchor: none`.
- `.spacer-dynamic` must NOT have a CSS transition.

### Known limitation — non-PWA Android browser

When opening the keyboard on non-PWA Android browser, the viewport resize
(`interactive-widget=resizes-content`) causes a small visual shift of the
chat content (~3px). This is native browser behavior — the browser adjusts
scroll position to keep the focused input visible in the smaller viewport.
This does not occur on PWA (standalone mode) because the keyboard behavior
differs. No fix is possible without removing `resizes-content`, which
would require a different keyboard handling approach (visualViewport API
with overlay mode).

### Scroll restoration

**Do not hide/fade the scroll area during restoration.** `visibility:
hidden` or `opacity: 0` cause a visible flash.

### Navigation — DO NOT CHANGE WITHOUT READING THIS WHOLE SECTION

The current model (the "fa605f6 + drawer-first" model) is the result
of multiple iterations across attempts that each broke something
different. **Three architectures have been tried and rejected.**
Before changing anything in `useNavigation.js`, `Shell.jsx`'s
navigation paths, or `Drawer/*.css`'s transitions, you must
internalize the desiderata, the anti-patterns, and the trade-offs
below. Otherwise we *will* re-implement a previously-rejected
design and ship a regression.

Lock-in tests live in `tests/navigation.spec.mjs` (tests 1–24).

#### Desiderata (what the user explicitly cares about)

1. **No "two drawers" artifact during Chrome Android swipe-back.**
   The back-gesture animation must not show the drawer mid-slide
   over the destination view. This is the most visible symptom and
   the headline reason this section exists.
2. **Drawer slide-in/out animations stay visible.** The user values
   the 250ms drawer transition. Any "snap-shut" workaround degrades
   UX and is rejected.
3. **One back-press to exit the PWA from the home view.** Not two,
   not "first back closes a phantom sentinel." Phone users
   instinctively map back-from-home to "leave the app."
4. **Drawer-close via overlay tap / X button does not navigate.**
   Closing the drawer must NEVER pop the navStack or change view.
   This was the most recent regression — every close path was
   over-popping.
5. **Drawer-first back behavior.** A back-gesture while the drawer
   is open closes the drawer ONLY. It does not also navigate. This
   matches user mental model on mobile.
6. **Back-gesture from a deep view (chat reached via drawer-tap)
   returns to the previous view.** One back = one nav.
7. **Drawer is conceptually a virtual route.** Open pushes a
   sentinel; close consumes it. The URL stays at `/` so this
   route-ness is invisible to users.

#### Architecture (how we satisfy them)

```
              ┌───────────────────────┐
              │ openDrawer            │
              │   pushState(null,'')  │──── browser history grows by 1
              │   drawerPushedRef=t   │
              │   setDrawerOpen(true) │
              └───────────────────────┘
                         │
                  drawer is open
                         │
        ┌────────────────┼─────────────────────┐
        │                │                     │
        v                v                     v
  closeDrawer       navTo(view)         user swipes back
  (X / overlay)     (drawer item tap)   (OS gesture)
        │                │                     │
        │ (drawerPushed? │ drawerPushed=false  │
        │  history.back  │ navStack.push(prior)│
        │  → handleBack) │ (no pushState)      │
        v                v                     v
  ──────────────  same handler ─────────────────
                   `handleBack`:
              ┌─ if drawerOpenRef && drawerPushedRef:
              │     close drawer state, return  ← drawer-first guard
              │
              └─ else:
                    pop navStack, restore view
```

Key load-bearing pieces:

- **`navTo` does NOT pushState.** This is the structural fix for the
  Chrome BFCache "two drawers" artifact. Browser history stays
  pinned to the entry above base (the drawer-sentinel from
  `openDrawer`). Chrome's snapshot of the entry being navigated TO
  on swipe-back was captured BEFORE any drawer interaction, so it's
  drawer-free. Test 21 (`tests/navigation.spec.mjs`) locks this in.
- **`closeDrawer` funnels through `history.back()`.** Every close
  path (overlay tap, X button, OS back-gesture) ends up calling
  `handleBack`. There is exactly ONE place that mutates the
  drawer-state during close. Tests 22–24 lock this in for each path.
- **`handleBack`'s drawer-first guard.** `if (drawerOpenRef.current
  && drawerPushedRef.current) { close drawer; return }`. Without
  this guard, closeDrawer's synthetic `history.back()` would over-
  pop `navStackRef` and unexpectedly navigate. Test 10 locks this
  in.
- **`drawerPushedRef` cleared in three places.** (a) `navTo` (the
  drawer-sentinel becomes the nav back-target instead of a drawer-
  close target). (b) `handleBack` after the drawer-first branch.
  (c) `handleBack` after the navStack-pop branch (defensive). A
  stale `true` causes the next `closeDrawer` to fire a spurious
  `history.back()`.

#### Anti-patterns (tried, rejected — do not silently re-implement)

| Approach | Tried in | Why rejected |
|---|---|---|
| **`navTo` pushes per-nav + drawer purely visual** (no pushState in drawer) | 84ca8b6 (current `main` until f1ce5cd, before this fix) | Looked clean; caused the "two drawers" BFCache artifact because every nav created a new entry whose snapshot Chrome cached mid-drawer-animation. |
| **`flushSync(setDrawerOpen(false))` before `pushState` in navTo** | 74d3800 | Insufficient. flushSync commits the React class change but the 250ms CSS `transform` transition keeps drawer pixels on screen for the snapshot. We tested the wrong invariant (DOM class) and shipped it confidently. |
| **Perpetual single-sentinel pattern** (one sentinel forever, re-pushed after each consumed back) | local 2026-04-26 (reverted before deploy) | Required an extra back-press to exit the PWA from the bottom of the in-app stack. The user explicitly rejected this UX cost. |
| **`closeDrawer` mutates drawer state directly + then `history.back()`** | fa605f6's original `closeDrawer` | Subtle bug: when the user opened drawer ON a deep view (e.g. chat reached via drawer-tap), navStack was non-empty. The `history.back()` fired the popstate handler whose check `if (navStack empty && drawer closed) return` did NOT early-return, so handleBack ran and popped navStack. Result: closing drawer over-navigated to a previous view. |
| **Snap-close drawer transition** (remove or zero the close transition) | not implemented, considered | User rejected: wants the slide-out animation visible in normal close paths. |
| **Drawer-as-route in URL** (e.g. `/?drawer=open`) | not implemented, considered | Adds visible URL noise; breaks no-shareable-URL contract; the structural BFCache fix doesn't depend on URL. |

If you find yourself proposing one of these, **stop and read this
section before writing code.** Each was a real ~half-day-or-more
detour that ended in revert.

#### Gotchas

- **Navigation API `intercept()` does NOT pop `history.length`.** It
  moves the active history index back without removing entries.
  Tests asserting `history.length` strict equality across drawer
  cycles will fail spuriously — the UX-relevant invariant is
  "active index returns + view unchanged + drawer closed." Tests
  3, 8, 15 reflect this; if you're tempted to tighten them, don't.
- **Don't add early-return guards in `openDrawer`/`closeDrawer`
  beyond what fa605f6 had.** The toggle in `Shell.jsx` already
  guards on `aria-expanded` so the click handlers are idempotent.
  Adding `if (drawerOpenRef.current) return` in `openDrawer` plus a
  synchronous `drawerOpenRef.current = true` set caused a visible
  "first drawer open is slow to render" regression on the user's
  phone (root cause not fully understood; suspected interaction
  with React 18 batching + the synchronous ref-set racing with
  state commit on the cold path).
- **`drawerPushedRef` is the single source of truth for "is there a
  drawer-sentinel above current entry?"**. It's a ref, not state,
  because it's mutated synchronously inside `navTo` and
  `closeDrawer` before async events fire. Don't move this to React
  state — it must be readable in the same JS task as the
  history-mutating call.
- **`Shell.newChat`'s `userInitiated` branch.** When the user
  invokes "new chat" from the drawer, `drawerPushedRef` is true
  and the drawer-sentinel becomes the back-target — we do NOT
  `pushState` in that case. When `newChat` is called from a
  draft/forceNew context (no drawer involved), we DO `pushState`
  to install a fresh sentinel above the chat the user came from.
  Subtle but correct.
- **`navStackRef` must be scrubbed on chat delete.**
  `Shell.deleteChat` filters `navStackRef.current` to remove
  entries whose `chatId` matches the deleted chat. Without this,
  back-gesture after delete navigates into a 404'd chat.
- **Edge case: deep-link arrival + click-to-open-app.** User taps
  a notification (lands on `/chat/<id>`). We parse, set state,
  `replaceState('/')`. No sentinel exists. User clicks "Open app"
  banner → `navTo('canvas', ...)` runs without a drawer-sentinel.
  Back from canvas exits PWA instead of returning to chat. This
  is a known small regression vs the perpetual-sentinel option;
  acceptable because (a) it requires the specific notification ->
  build-app -> open-app -> swipe-back flow, (b) fixing it would
  require either a perpetual sentinel (rejected) or per-nav
  pushState (the BFCache regression).

### Streaming rendering

Block-memoized markdown renderer: `marked.lexer()` tokenizes into blocks, each rendered as a `React.memo()` component. Only the last (active) block re-renders as tokens arrive. Text tokens are buffered and drained via `requestAnimationFrame` for a typewriter effect (~3 chars/frame at 60fps). Don't replace this with streaming-markdown or innerHTML approaches — they lose control over individual element types.

### Voice input

Uses `SpeechRecognition` with `continuous: false` and `interimResults: true`. Sessions auto-stop after silence; `onend` restarts with a new instance.

Don't use `continuous: true` — it's broken on Android Chrome (results array grows indefinitely, duplicate events). Filter `confidence === 0` finals — Android Chrome fires duplicates. The `onChange` guard (`if (listeningRef.current) return`) blocks Chrome's OS dictation layer from racing with `onresult`.

### Session isolation

Each chat stores a `session_id` from the CLI. First message starts a fresh session; subsequent messages use `--resume {session_id}`. This prevents cross-chat context leakage.

### System prompt

The skill (`skill/agent-skill.md`) is passed as `--system-prompt-file` only on the first message. Resumed sessions inherit the system prompt from creation — start a fresh chat after deploying skill changes.

Dynamic per-session data (experience file, timezone) is injected into the first user message as an `<agent_experience>` block, not the system prompt. Static content goes first for prompt cache efficiency.

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
