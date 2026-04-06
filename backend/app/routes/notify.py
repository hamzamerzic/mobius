"""Lightweight event notification endpoint.

The agent calls this after making changes (theme, app, shell rebuild)
so the frontend can react immediately via the active chat broadcast.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import models
from app.broadcast import get_active_broadcast, get_all_active_broadcasts
from app.deps import get_current_owner

router = APIRouter(prefix="/api/notify", tags=["notify"])

ALLOWED_EVENT_TYPES = {
  "theme_updated",
  "app_updated",
  "shell_rebuilding",
  "shell_rebuilt",
  "shell_rebuild_failed",
}


class NotifyBody(BaseModel):
  type: str
  appId: str | None = None
  error: str | None = None


@router.post("", status_code=204)
def notify(
  body: NotifyBody,
  _owner: models.Owner = Depends(get_current_owner),
):
  """Publish a system event to the active chat broadcast.

  Requires a valid JWT.  If no broadcast is active (no agent running),
  the event is silently dropped — nobody is listening.
  """
  if body.type not in ALLOWED_EVENT_TYPES:
    raise HTTPException(422, f"unknown event type: {body.type}")

  event: dict = {"type": body.type}
  if body.appId is not None:
    event["appId"] = body.appId
  if body.error is not None:
    event["error"] = body.error

  # Publish to all running broadcasts so concurrent chats all receive
  # system events (theme changes, shell rebuilds, etc.).  Falls back to
  # the single active broadcast for compatibility with callers that don't
  # know which chats are running.
  targets = get_all_active_broadcasts()
  if not targets:
    bc = get_active_broadcast()
    if bc is not None:
      targets = [bc]
  for bc in targets:
    bc.publish(event)
