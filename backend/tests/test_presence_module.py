"""Unit tests for the presence module (ticket 033).

Locks in the watcher-presence contract used by push.notify_owner to
decide whether to send a push notification:

  - empty chat_id → False (defensive)
  - no broadcast → False
  - broadcast exists but no subscribers → False
  - broadcast exists with at least one subscriber → True
  - mark_completed clears subscribers → False afterward
  - fresh-query: a value is not cached across calls
"""

from __future__ import annotations

import asyncio

from app import presence
from app.broadcast import create_broadcast, get_broadcast, remove_broadcast


def test_has_watchers_false_on_empty_chat_id():
  assert presence.has_watchers("") is False
  assert presence.has_watchers(None) is False  # type: ignore[arg-type]


def test_has_watchers_false_when_no_broadcast_exists():
  remove_broadcast("never-created")
  assert presence.has_watchers("never-created") is False


def test_has_watchers_false_when_broadcast_has_no_subscribers():
  bc = create_broadcast("no-subs")
  try:
    assert len(bc.subscribers) == 0
    assert presence.has_watchers("no-subs") is False
  finally:
    remove_broadcast("no-subs")


def test_has_watchers_true_when_at_least_one_subscriber():
  async def go():
    bc = create_broadcast("with-sub")
    try:
      _catch_up, q = bc.subscribe()
      try:
        assert presence.has_watchers("with-sub") is True
      finally:
        bc.unsubscribe(q)
    finally:
      remove_broadcast("with-sub")

  asyncio.run(go())


def test_has_watchers_false_after_mark_completed():
  """mark_completed clears subscribers as a side-effect. presence
  reflects that immediately — no caching."""
  async def go():
    bc = create_broadcast("complete-then-check")
    try:
      _catch_up, _q = bc.subscribe()
      assert presence.has_watchers("complete-then-check") is True
      bc.mark_completed()
      assert presence.has_watchers("complete-then-check") is False
    finally:
      remove_broadcast("complete-then-check")

  asyncio.run(go())


def test_has_watchers_fresh_query_each_call():
  """A subscribe/unsubscribe cycle between two calls flips the
  boolean — proving the second call is NOT a cached read."""
  async def go():
    bc = create_broadcast("fresh-query")
    try:
      assert presence.has_watchers("fresh-query") is False
      _catch_up, q = bc.subscribe()
      assert presence.has_watchers("fresh-query") is True
      bc.unsubscribe(q)
      assert presence.has_watchers("fresh-query") is False
    finally:
      remove_broadcast("fresh-query")

  asyncio.run(go())
