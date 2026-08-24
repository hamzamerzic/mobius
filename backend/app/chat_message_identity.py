"""Pure assistant-message identity matching shared by chat read/write paths."""

from __future__ import annotations


def assistant_message_index(messages: list, message: dict) -> int:
  """Locate the assistant row owned by ``message``.

  Current snapshots carry the segment's durable ``id`` and may update that
  exact row even when a hidden same-turn answer follows it. Id-less snapshots
  are historical/test compatibility only and retain the former trailing-row
  rule. One rolling-upgrade exception lets an explicit id adopt a trailing
  id-less assistant; it can never cross a later turn or a different id.
  """
  message_id = message.get("id") if isinstance(message, dict) else None
  if message_id is not None:
    target = str(message_id)
    for index, candidate in enumerate(messages):
      if (
        isinstance(candidate, dict)
        and candidate.get("role") == "assistant"
        and candidate.get("id") is not None
        and str(candidate.get("id")) == target
      ):
        return index
    if (
      messages
      and messages[-1].get("role") == "assistant"
      and messages[-1].get("id") is None
    ):
      # Rolling upgrade only: the former persistence shape has no identity to
      # compare. A trailing id-less assistant is the one safe adoption point;
      # any explicit id or later visible turn proves this is a new segment.
      return len(messages) - 1
    return -1
  if messages and messages[-1].get("role") == "assistant":
    return len(messages) - 1
  return -1
