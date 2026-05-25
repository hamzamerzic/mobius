"""Tracks who's actively watching a chat broadcast (ticket 033).

`push.notify_owner` uses this module to decide whether to send a
push notification — skip if a live SSE subscriber is watching, since
the in-tab UX already surfaces the event.

The presence signal is derived: the broadcast registry already knows
its live subscribers (the `subscribers` list on each ChatBroadcast).
This module is the PUBLIC contract — `has_watchers(chat_id) -> bool`.
Callers must not read `bc.subscribers` directly.

Exception: `routes/debug.py` reads `subscriber_count` for the debug
status payload (observability). That's an inline read, not a presence
check, and is explicitly allowed.

No caching. SSE disconnect races are common; a cached value risks
suppressing a real-need notification because a stale watcher entry
hadn't been reaped yet. Each call freshly queries the broadcast
registry.
"""

from __future__ import annotations

from app.broadcast import get_broadcast


def has_watchers(chat_id: str) -> bool:
  """True if at least one live SSE subscriber is currently watching
  this chat's broadcast.

  Returns False when:
    - chat_id is empty / None
    - no broadcast exists for the chat
    - the broadcast exists but its subscribers list is empty
      (e.g. the chat already completed; `mark_completed` clears
      subscribers as part of its terminal flow)
  """
  if not chat_id:
    return False
  bc = get_broadcast(chat_id)
  if bc is None:
    return False
  return len(bc.subscribers) > 0
