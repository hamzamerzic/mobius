"""Debug and observability endpoints.

Provides structured access to chat logs, active processes, and broadcast
state.  All endpoints require authentication.  The agent uses these when
debugging issues instead of ad-hoc debug endpoints.
"""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from app import models
from app.broadcast import get_broadcast, get_all_active_broadcasts
from app.chat import get_active_procs, get_starting
from app.config import get_settings
from app.deps import get_current_owner

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/status")
def debug_status(
  _owner: models.Owner = Depends(get_current_owner),
):
  """Returns active agent processes, broadcasts, and starting state."""
  active = []
  for chat_id, proc in get_active_procs().items():
    active.append({
      "chat_id": chat_id,
      "pid": proc.pid,
      "running": proc.returncode is None,
      "returncode": proc.returncode,
    })

  broadcasts = []
  for bc in get_all_active_broadcasts():
    broadcasts.append({
      "chat_id": bc.chat_id,
      "running": bc.running,
      "event_count": len(bc.event_log),
      "subscriber_count": len(bc.subscribers),
    })

  return {
    "active_procs": active,
    "starting": list(get_starting()),
    "broadcasts": broadcasts,
  }


@router.get("/logs")
def debug_logs(
  _owner: models.Owner = Depends(get_current_owner),
  lines: int = Query(default=100, ge=1, le=5000),
  chat_id: str | None = Query(default=None),
):
  """Returns the last N lines from the chat log, optionally filtered by
  chat_id.  Reads from the end of the file efficiently."""
  settings = get_settings()
  log_path = Path(settings.data_dir) / "logs" / "chat.log"
  if not log_path.exists():
    return {"lines": [], "total_size": 0}

  total_size = log_path.stat().st_size

  # Read the last chunk of the file (generous buffer to get enough lines).
  buf_size = min(total_size, lines * 500)
  with open(log_path, "rb") as f:
    f.seek(max(0, total_size - buf_size))
    tail = f.read().decode("utf-8", errors="replace")

  all_lines = tail.strip().split("\n")

  if chat_id:
    all_lines = [l for l in all_lines if chat_id in l]

  result = all_lines[-lines:]
  return {"lines": result, "total_size": total_size}
