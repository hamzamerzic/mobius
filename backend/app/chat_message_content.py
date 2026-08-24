"""Pure helpers for server-added chat message content."""

from __future__ import annotations

import re


# The send path appends this trusted block so providers can inspect uploads.
# Product logic must reason about the owner's text without treating that hidden
# transport context as part of a command or control word.
_UPLOAD_AUGMENTATION_RE = re.compile(
  r"\n*\[Files in this session:\n.*\]\s*$", re.DOTALL
)


def strip_upload_augmentation(content: str) -> str:
  """Return stored user content without its server-added upload manifest."""
  if not content:
    return content
  return _UPLOAD_AUGMENTATION_RE.sub("", content).rstrip()
