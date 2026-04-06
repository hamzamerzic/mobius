"""Per-chat event broadcast for SSE delivery.

Decouples the CLI subprocess from SSE clients.  The subprocess
publishes events here; any number of SSE clients can subscribe
and receive a catch-up burst of prior events plus live streaming.
"""

import asyncio
import logging
import time
from typing import Optional

log = logging.getLogger("moebius.broadcast")

# Global registry of active broadcasts, keyed by chat_id.
_broadcasts: dict[str, "ChatBroadcast"] = {}

# The notify endpoint needs to find the running broadcast without
# knowing the chat ID.  Since Möbius is single-owner, there is at
# most one active broadcast at a time.  run_chat() sets this on
# start and clears it in its finally block.
_active_broadcast: "ChatBroadcast | None" = None


def set_active_broadcast(bc: "ChatBroadcast | None") -> None:
  """Track the broadcast for the currently running agent chat."""
  global _active_broadcast
  _active_broadcast = bc


def get_active_broadcast() -> "ChatBroadcast | None":
  """Return the active broadcast, or None if no agent is running."""
  return _active_broadcast


# How long a completed broadcast stays alive for late reconnectors.
_COMPLETED_TTL_SECS = 30


class ChatBroadcast:
  """Event bus for a single chat's agent session."""

  def __init__(self, chat_id: str):
    self.chat_id = chat_id
    self.event_log: list[dict] = []
    self.subscribers: list[asyncio.Queue] = []
    self.running = True
    self.completed_at: Optional[float] = None

  def publish(self, event: dict):
    """Appends event to log and pushes to all subscriber queues."""
    self.event_log.append(event)
    for q in self.subscribers:
      try:
        q.put_nowait(event)
      except asyncio.QueueFull:
        log.warning("subscriber queue full, dropping event")

  def subscribe(self) -> tuple[list[dict], asyncio.Queue]:
    """Returns (catch_up_events, live_queue) for a new subscriber."""
    q: asyncio.Queue = asyncio.Queue(maxsize=4096)
    catch_up = list(self.event_log)
    self.subscribers.append(q)
    return catch_up, q

  def unsubscribe(self, q: asyncio.Queue):
    """Removes a subscriber queue."""
    try:
      self.subscribers.remove(q)
    except ValueError:
      pass

  def mark_completed(self):
    """Marks the broadcast as done and schedules cleanup."""
    self.running = False
    self.completed_at = time.time()
    # Push a sentinel so subscribers unblock.
    for q in self.subscribers:
      try:
        q.put_nowait(None)
      except asyncio.QueueFull:
        pass


def get_all_active_broadcasts() -> list["ChatBroadcast"]:
  """Return all broadcasts that are still running (agent not finished)."""
  return [bc for bc in _broadcasts.values() if bc.running]


def get_broadcast(chat_id: str) -> Optional["ChatBroadcast"]:
  """Returns the active broadcast for a chat, or None."""
  bc = _broadcasts.get(chat_id)
  if bc and not bc.running and bc.completed_at:
    if time.time() - bc.completed_at > _COMPLETED_TTL_SECS:
      _broadcasts.pop(chat_id, None)
      return None
  return bc


def create_broadcast(chat_id: str) -> "ChatBroadcast":
  """Creates and registers a new broadcast for a chat."""
  # Clean up any stale broadcast.
  _broadcasts.pop(chat_id, None)
  bc = ChatBroadcast(chat_id)
  _broadcasts[chat_id] = bc
  return bc


def remove_broadcast(chat_id: str):
  """Removes a broadcast immediately."""
  _broadcasts.pop(chat_id, None)
