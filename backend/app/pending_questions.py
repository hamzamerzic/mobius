"""Shared `PendingQuestion` definition for the AskUserQuestion flow.

The SDK runner constructs one inside `can_use_tool` and inserts it
into the registry owned by `app.questions` (see `_pending` there).
Routes resolve the future via `questions.claim()` + setting the
result, or `questions.deliver_answer()`. Keeping the class in its
own module avoids a circular import (questions → runner; runner
needs the class).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass
class PendingQuestion:
  """A question waiting for the partner's AskUserQuestion answer.

  Lives in `questions._pending[chat_id]` while the SDK runner's
  `can_use_tool` callback is blocked on `await future`. The
  `POST /messages` handler resolves `future` when an answers payload
  arrives, which unblocks the callback and lets the SDK continue.
  """

  question_id: str
  questions: list[dict[str, Any]]
  future: asyncio.Future
