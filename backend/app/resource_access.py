"""Shared resource-access helpers for route handlers.

Centralizes the `db.query(Chat).filter(Chat.id == ..., Chat.deleted_at
IS NULL).first()` pattern that multiple route files copy. A single
implementation means a future correctness fix (e.g. tightening the
soft-delete check) propagates everywhere instead of needing N edits.

Scope is intentionally narrow — ACTIVE chat reads only. Routes whose
lookup intentionally diverges from the soft-delete filter (the
delete flow at `routes/chats.py:376` queries by id without the
filter because it is actively setting `deleted_at`; the recover
flow at `routes/chats.py:392-395` queries with the INVERSE filter)
stay inline. This module is not the place to capture both behaviors
behind a flag — a flag would just push the special-case detail to
every caller.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models


def get_active_chat_or_404(
  db: Session, chat_id: str,
) -> models.Chat:
  """Fetches a non-soft-deleted Chat by id, raising 404 otherwise.

  Sync (not async) because the underlying SQLAlchemy `Session` is
  sync — there is no I/O await to surface here, and a sync helper
  is callable from both sync and async route handlers (most chat
  routes are sync `def`; a few like `send_message` are `async def`).

  The Chat model has no `owner_id` column (single-owner installation;
  see `models.py:24-50`), so owner-scoping is not this helper's job —
  it happens upstream via `deps.get_current_owner` on the route.

  Args:
    db: SQLAlchemy session.
    chat_id: The chat id (string primary key).

  Returns:
    The matching Chat row.

  Raises:
    HTTPException: 404 when no row matches OR the row is soft-deleted.
  """
  chat = db.query(models.Chat).filter(
    models.Chat.id == chat_id,
    models.Chat.deleted_at.is_(None),
  ).first()
  if chat is None:
    raise HTTPException(status_code=404, detail="Chat not found.")
  return chat
