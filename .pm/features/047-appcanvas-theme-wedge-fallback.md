---
id: "047"
title: AppCanvas wedges if theme cache never populates
status: done
priority: 11
hook: After commit 28264d2 (sendInit gated on !theme), if theme query never resolves (Shell didn't run useTheme, query failed silently), iframe sits in "Loading…" until the 10s timeout — worse than the cold-cache flash the gate was meant to fix.
created: 2026-05-25
---

## Why

Surfaced by the pre-prod review (2026-05-25, codex pass).

Commit 28264d2 added `if (!theme) return` to `sendInit()` in
`frontend/src/components/AppCanvas/AppCanvas.jsx:99` to prevent a
visible flash on cold theme cache. The downside: AppCanvas reads
`['theme']` with `enabled: false` (line 65) — it's a cache-only
subscription. The only in-tree writer of that cache slot is
`useTheme()` in Shell.

If Shell's theme query hasn't resolved by the time AppCanvas
renders (deep-link arrival before Shell hydrates; useTheme query
failed; cache evicted), `theme` stays `undefined` and `sendInit`
hard-returns forever. The iframe then sits in its "Loading…"
state until `app-frame.html`'s 10s timeout, after which it shows
an error — worse UX than the original flash.

In practice today this is unlikely: Shell is the parent of
AppCanvas, so useTheme has been mounted before AppCanvas mounts.
But "unlikely" is exactly the silent + catastrophic + recoverable-
only-by-reload failure mode CLAUDE.md flags as worth defending
against in substrate code.

## What

Two options; pick one in the design pass:

### Option A: AppCanvas fetches on cache miss

Change the useQuery at AppCanvas.jsx:63-67 from `enabled: false`
to `enabled: !theme` (or always-enabled with `staleTime: Infinity`),
so AppCanvas itself triggers a fetch if the cache is cold. Adds
one extra request per cold-mount of AppCanvas; aligns with the
intent of useQuery as a fetch-or-subscribe.

### Option B: bounded fallback

Keep `enabled: false` but add a setTimeout (e.g. 500ms) — if
theme still hasn't arrived, send init with a fallback theme
(empty CSS + a neutral bg from config). Iframe renders fallback,
then the existing `frame-theme` effect re-applies real theme
when it arrives — restoring the pre-28264d2 behavior but bounded.

Option A is cleaner and matches React Query idioms. Option B
preserves the no-extra-request property.

## Done when

- [ ] AppCanvas can never wedge waiting for a theme that never
      arrives. Worst case is a brief flash, not a 10s timeout.
- [ ] Manual repro: open AppCanvas with `queryClient` lacking the
      `['theme']` entry — iframe still loads within ~1s.
- [ ] No regression in the cold-cache no-flash behavior 28264d2
      shipped — Shell's useTheme path must still deliver init
      with a real theme on the common path.
