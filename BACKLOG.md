# Möbius backlog

Running list of user-reported items and ideas, ordered roughly by
priority within each section. Update as items ship or get re-scoped.

## In progress

_(none right now)_

## Next up — UX polish

- **App-back-refresh feels like a reload.** When the last view was a
  mini-app and the user navigates away then back, the app appears to
  reload (iframe re-fetches module). Should preserve scroll/state
  similarly to how chats now do via the query cache. Likely fix:
  iframe's `src` is hashed by `appVersion` which forces remount; or
  the React `<AppCanvas key={...}>` is too aggressive.
- **BFCache "two drawers" cosmetic.** Navigating away from
  drawer-open captures the drawer-open state in the BFCache snapshot.
  `flushSync(() => setDrawerOpen(false))` before `pushState` in
  `navTo` would fix it deterministically. ~3 lines.
- **Drawer chat list / apps list still imperative.** Migrate to
  `useChats` / `useApps` queries (the foundation is in place; this
  is the mechanical follow-up to the TanStack work).

## Next up — agent / iteration loop

- **Run Session 13 with the new prompt mix** (vague →
  trivial-then-escalate → directive). Was added to the demo playbook
  but never executed.
- **Read prod chat logs since Session 12** and upstream learnings
  into the seed. Specifically: the ISS chat where the agent figured
  out texture caching / smoothing — there's reusable knowledge there.
- **Speed up agent startup tool-calls.** The agent often does ~5
  Read/grep calls before producing visible work. Investigate which
  are necessary, whether the experience file already documents what
  it's looking for, and whether the agent can parallelize the
  remaining reads. Goal: reduce time-to-first-meaningful-action
  WITHOUT letting the agent skip its clarify gate.
- **Screenshot viewport mismatch.** The screenshots the agent takes
  via agent-browser appear smaller than the user's actual phone
  viewport. Either the agent is using a default viewport (likely
  ~360×640 fallback) instead of the partner's `Viewport: WxH` from
  context, or `agent-browser set viewport` isn't being called.
  Check the seed's screenshot section + verify on a real run.

## Future — architecture

- **`chat_updated` SSE event** for server-driven cache invalidation
  when chats are mutated outside the streaming path (e.g. recovery,
  backend-only edits).
- **Owner-status `useQuery`** to replace the imperative fetch in
  `App.jsx`.
- **`flushSync` / React-18 transition opt-ins** to formalize
  before-paint scroll restoration in `ChatView`.

## Closed (recent)

- (84ca8b6) Drawer rewrite: purely visual state, navigation pushes /
  pops history. Eliminated the +1 history leak and the "back closes
  drawer first" half-step.
- (bed070b) Back-nav jitter + send-flash fix.
- (cc1cbe3) TanStack Query data layer + IndexedDB persistence.
- (eb368f9) Service-worker timeout, vendored three.js, Claude CLI
  bump, cron PATH fix, scroll guard.

## Reading list

Things the user has linked / referenced and would like incorporated
where applicable:

- https://slicker.me/webdev/pwas-offline-first.html — applied: SW
  network-first timeout, persistent storage request, IndexedDB
  cache for chat queries. Deferred: full local-first / IndexedDB
  primary store / CRDTs (overkill for single-owner Möbius).
