"""Lightweight event notification endpoint + shell-level SSE stream.

POST /api/notify lets the agent emit system events (theme, app,
shell rebuild). They land on both the SystemBroadcast (Shell-level
listener, always live) and any active per-chat broadcasts (so the
chat catch-up replay stays coherent).

GET /api/events/system is the Shell's persistent SSE subscription.
Independent of any chat — survives navigation so app_updated /
theme_updated reach Shell even when the user is on the canvas or
settings view.
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import models
from app.broadcast import (
  get_active_broadcast,
  get_all_active_broadcasts,
  get_system_broadcast,
)
from app.deps import get_current_owner

router = APIRouter(tags=["notify"])
log = logging.getLogger(__name__)

# Keepalive cadence for the shell-level SSE — same value used in
# chats_stream so proxies behave consistently.
_KEEPALIVE_INTERVAL = 30

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


@router.post("/api/notify", status_code=204)
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

  # ALWAYS publish to the system broadcast — Shell subscribes to it
  # for system events regardless of which view the user is on.
  # Without this, an app_updated emitted after the chat finished
  # streaming (or while the user is on the canvas / settings) would
  # have nowhere to land: chat broadcasts close shortly after the
  # turn ends, and the canvas view never had a subscription.
  get_system_broadcast().publish(event)

  # Also publish to running per-chat broadcasts so any currently
  # active chat catch-up replay includes the event in order. New
  # subscribers connecting to a stale event log get the event too,
  # which keeps existing chat-level UI invariants.
  targets = get_all_active_broadcasts()
  if not targets:
    bc = get_active_broadcast()
    if bc is not None:
      targets = [bc]
  for bc in targets:
    bc.publish(event)


@router.get("/api/events/system")
async def stream_system_events(
  request: Request,
  _owner: models.Owner = Depends(get_current_owner),
):
  """Shell-level SSE: streams system events for the lifetime of the
  Shell, regardless of which view (chat / canvas / settings) is
  mounted. The Shell subscribes once on mount and keeps the
  connection open until logout / unmount.

  Keepalive cadence matches the chat stream so reverse proxies see
  consistent traffic patterns.
  """
  queue = get_system_broadcast().subscribe()

  async def generate():
    try:
      # Hello so the client knows the connection is live before any
      # real event arrives. EventSource clients ignore unknown types
      # but the message still flushes Caddy / nginx buffers.
      yield f"data: {json.dumps({'type': 'system_stream_open'})}\n\n"
      while True:
        if await request.is_disconnected():
          break
        try:
          event = await asyncio.wait_for(
            queue.get(), timeout=_KEEPALIVE_INTERVAL,
          )
        except asyncio.TimeoutError:
          yield ": keepalive\n\n"
          continue
        yield f"data: {json.dumps(event)}\n\n"
    finally:
      get_system_broadcast().unsubscribe(queue)

  return StreamingResponse(
    generate(),
    media_type="text/event-stream",
    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
  )
