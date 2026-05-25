"""Per-chat pending-message queue (ticket 033).

Three operations race on `chat.pending_messages` (the JSON column):
append (POST /messages), cancel (DELETE /pending), and promote
(turn-end drain). Without serialization, two concurrent operations
read the same snapshot and one commit overwrites the other —
queue entries vanish silently. The per-chat asyncio.Lock returned
by `get_lock` makes all three pairwise-atomic; every caller holds
the lock around its read-modify-write.

Lock-storage correctness invariants:

  - `_locks` is a `WeakValueDictionary`. Entries collect when no
    caller holds a reference, so the dict can't grow unbounded
    across the long-running container.
  - `get_lock` is fully synchronous — NO `await` between the get +
    None-check + insert. The asyncio scheduler can only run
    another task at an await point, so two concurrent callers for
    the same chat_id walk through the function in series and
    receive the same `asyncio.Lock` instance. Introducing an
    await mid-method here would break the atomic get-or-create
    and let two callers get two different locks for the same
    chat — silently re-racing the queue.

`drain_and_release` is a composite primitive: take the lock,
promote the head of the queue, and if the queue was empty release
the `_starting` claim and forget the chat — all under one lock
acquisition. It does NOT call back into `run_chat`; the caller
(chat.py:_run_chat_impl) schedules the continuation AFTER the
lock releases, exactly as before the refactor. Keeping that order
identical is what makes this a behavior-preserving move.
"""

from __future__ import annotations

import asyncio
import weakref
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import models, schemas


_locks: "weakref.WeakValueDictionary[str, asyncio.Lock]" = (
  weakref.WeakValueDictionary()
)


def get_lock(chat_id: str) -> asyncio.Lock:
  """Returns the per-chat queue lock, creating it if needed.

  Atomic get-or-create — see module docstring for why this MUST
  stay synchronous.
  """
  lock = _locks.get(chat_id)
  if lock is None:
    lock = asyncio.Lock()
    _locks[chat_id] = lock
  return lock


def reset_for_tests() -> None:
  """Drops the lock registry. Test fixtures call this so a lock
  held by a leaked task from a prior test can't be returned to
  the next test's caller."""
  global _locks
  _locks = weakref.WeakValueDictionary()


def _get_logger():
  import logging
  return logging.getLogger("moebius.chat")


def promote_pending_messages_locked(
  db: Session,
  chat_id: str,
) -> tuple[list[schemas.ChatMessage], dict | None, str | None]:
  """Inner promote logic. PRECONDITION: caller holds the per-chat
  queue lock. This sync variant exists so the finally block in
  _run_chat_impl can do its 'late-drain + release _starting' critical
  section atomically under a single lock acquisition without needing
  re-entrant locks.

  Returns (next_messages, first_pending, session_id) on success.
  Returns ([], None, session_id) when the pending queue is empty or
  when next_messages construction fails (malformed transcript entry).
  """
  if not chat_id:
    return [], None, None
  chat = db.query(models.Chat).filter(models.Chat.id == chat_id).first()
  if not chat:
    return [], None, None
  # Refresh inside the lock so we see commits from any append or
  # cancel that completed while we waited.
  db.refresh(chat)
  pending = list(chat.pending_messages or [])
  if not pending:
    return [], None, chat.session_id

  existing = list(chat.messages or [])
  first_pending = pending[0]
  # Build next_messages BEFORE committing so a malformed transcript
  # entry can't silently consume a pending turn. If construction
  # raises, log and leave the queue intact for retry.
  try:
    next_messages = [
      schemas.ChatMessage(
        role=m.get("role", "user"),
        content=m.get("content", "") or "",
      )
      for m in existing
    ]
    next_messages.append(
      schemas.ChatMessage(
        role=first_pending.get("role", "user"),
        content=first_pending.get("content", "") or "",
      )
    )
  except Exception:
    _get_logger().exception(
      "promote: next_messages construction failed chat_id=%s — "
      "leaving pending queue intact", chat_id,
    )
    return [], None, chat.session_id

  chat.messages = existing + [first_pending]
  chat.pending_messages = pending[1:]
  chat.updated_at = datetime.now(UTC)
  db.commit()

  return next_messages, first_pending, chat.session_id


async def promote_pending_messages(
  db: Session,
  chat_id: str,
) -> tuple[list[schemas.ChatMessage], dict | None, str | None]:
  """Atomically promotes the head of the pending queue into the
  transcript.

  Held under the per-chat queue lock so the read-modify-write on
  pending_messages doesn't race with append (POST /messages) or
  cancel (DELETE /pending/{ts}).

  This function does NOT claim _starting — the caller is responsible
  for ensuring exclusive promotion (e.g., via mark_starting before
  call in stale-pending path, or by virtue of being the only finally
  block for a given run in the turn-end path). Adding mark_starting
  here was a round-7 over-engineering that broke the finally path:
  _starting still contains the original send's claim when the finally
  fires, so the in-promote mark_starting always returned False and
  no queued turn ever got promoted in production.
  """
  if not chat_id:
    return [], None, None
  async with get_lock(chat_id):
    return promote_pending_messages_locked(db, chat_id)


async def drain_and_release(
  db: Session,
  chat_id: str,
  we_own_gen: bool,
  *,
  discard_starting,
  forget_chat,
) -> tuple[dict | None, list, str | None]:
  """End-of-turn queue drain. Returns (next_user, next_messages,
  next_session_id) for the caller to publish + schedule.

  Under the per-chat queue lock:
    - Promotes the head of pending_messages (if any).
    - If nothing to promote AND we_own_gen, releases _starting so
      any subsequent POST sees is_chat_running=False and starts a
      fresh run, then forgets the chat (drops the per-chat
      generation counter so long-running containers don't
      accumulate one entry per chat-ever-touched).

  Doing this in a single locked critical section closes the race
  between the run_chat finally and a POST that arrives in the window
  after the subprocess exits but before _starting is released. Both
  ends serialize on the same lock; whichever side wins ordering, the
  message is either promoted here or POST takes the start path.

  When we_own_gen is False (Stop bumped the gen), we must not
  promote or release _starting — the newer owner (Stop, or the
  continuation it scheduled) is responsible for those.

  `discard_starting` and `forget_chat` are injected so this module
  stays free of an import-cycle back into chat.py / runner_registry.
  Caller (chat.py:_run_chat_impl) keeps responsibility for the
  post-lock `_schedule_continuation` call — this function does NOT
  schedule continuations or call back into `run_chat`.
  """
  if not we_own_gen:
    return None, [], None
  async with get_lock(chat_id):
    next_messages, first_pending, next_session_id = (
      promote_pending_messages_locked(db, chat_id)
    )
    if first_pending is None:
      discard_starting(chat_id)
      forget_chat(chat_id)
    return first_pending, next_messages, next_session_id
