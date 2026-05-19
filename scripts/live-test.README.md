# live-test.sh — Möbius live UI smoke tests

End-to-end interactive flows driven through a real browser
(`agent-browser`, iPhone 12 emulation) against the **mobius-test**
container on port 8001. Never touches prod.

## Why agent-browser, not Playwright

The repo already has a Playwright config (`tests/`) for unit-style
component checks. `live-test.sh` is for behaviors that only show up
with a real mobile-emulated browser, a live SSE stream, and the real
Claude/Codex subprocesses — most importantly the sacred-spacer scroll
math, the queued-messages tray, and the touch-primary blur path. None
of those are meaningful without a true browser and a live backend.

`agent-browser` also pairs with `ab-liveview` so you can watch the
session run in your code-server proxy at
`https://code.hamzamerzic.info/proxy/9224/` while the script drives.

## Run

```bash
# Full fresh build (5-10 min) + all 5 flows:
bash scripts/live-test.sh

# Reuse current mobius-test (skip rebuild):
SKIP_REBUILD=1 bash scripts/live-test.sh

# Subset of flows:
FLOWS="3 5" bash scripts/live-test.sh
```

Artifacts (screenshots, summary, chat.log snapshot) land in
`/tmp/mobius-live-test/`.

## Flows

| # | Flow | What it asserts |
|---|------|-----------------|
| 1 | Multi-message ordering | After each send, the user message's bounding-box `top` ≤ 320px (pinned to top by the sacred spacer). API `/api/chats/{id}` confirms ordering matches send order. |
| 2 | Keyboard dismiss | Textarea is `document.activeElement` before send; is **not** after send. Verifies the `_isTouchPrimary` blur path in `ChatView.jsx:770`. |
| 3 | Queue while streaming | After sending a slow turn + 2 follow-ups, the tray (`[aria-label="Queued messages"]`) shows exactly 2 `[role="listitem"]` rows, and `pending_messages` in the DB matches. |
| 4 | Provider switching | `POST /api/settings {provider: codex}` flips owner.provider. A new chat sent afterward shows `provider=Codex` in `/data/logs/chat.log`; the Claude baseline chat shows `provider=Claude Code`. |
| 5 | Cancel queued message | After clicking X on the first queued row, tray shrinks by exactly one and DB `pending_messages` length decreases to match. |

## Soft-keyboard reality check

Headless Chrome does **not** render a soft keyboard, regardless of
`Page.setTouchEmulationEnabled` or device-emulation profile. CDP
exposes `Page.setTouchEmulationEnabled` and `Emulation.setEmitTouchEventsForMouse`,
neither of which paint a keyboard. What we **can** verify (and what
matters to mobile users) is the JS contract: focusing the textarea
opens the keyboard; blurring it dismisses. We make `matchMedia('(hover:
none) and (pointer: coarse)')` return `true` (via
`agent-browser set device "iPhone 12"`), then assert that
`document.activeElement` flips off the textarea on Send. That is the
exact signal the OS uses to close the keyboard, so this is the right
JS-level proxy.

For a visual demo of the keyboard actually appearing, you would need a
real device or an emulator like the Android emulator with an
ADB-connected Chrome instance — out of scope for a CI-style script.

## Provider verification

`backend/app/chat.py:629` logs

```
chat start chat_id=<id> provider=<Claude Code|Codex> session=<id> msg_len=<n>
```

for every turn. The script greps that line by `chat_id` and asserts
the right provider ran. If Codex CLI auth isn't installed in the
container the Codex chat will fail to start a session, but the
`provider=Codex` log line still fires before the failure — that's the
signal we want.

## Selectors used

| What | Selector | Source |
|------|----------|--------|
| Textarea | `placeholder="Message the agent..."` | ChatView.jsx:1178 |
| Send button | `aria-label="Send"` | ChatView.jsx:1193 |
| Queued tray | `[aria-label="Queued messages"]` | QueuedMessages.jsx:40 |
| Cancel button | `aria-label="Cancel queued message"` | QueuedMessages.jsx:90 |
| Stop button | `aria-label="Stop"` | ChatView.jsx:1182 |

All are stable accessibility attributes (kept for a11y reasons), so
they're safer to bind to than CSS class names.

## Safety

- Refuses to run if `TEST_PORT=8000` (the prod port).
- Container creds copied from the host's `~/.claude/.credentials.json`
  — never from the prod container (matches the agent-test runbook).
- Cleans previous volume on full rebuild so each run starts blank.
