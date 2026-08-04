"""Cross-process lease for Mobius-owned JavaScript build processes."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import IO


class BuildLease:
  """An acquired OS lease released on close or context exit."""

  def __init__(self, handle: IO[str]) -> None:
    self._handle = handle

  def close(self) -> None:
    if self._handle.closed:
      return
    try:
      fcntl.flock(self._handle, fcntl.LOCK_UN)
    finally:
      self._handle.close()

  def __enter__(self) -> "BuildLease":
    return self

  def __exit__(self, *_exc: object) -> None:
    self.close()


def build_lease_path() -> Path:
  """Return the one lease shared by shell Vite and mini-app Rolldown."""
  return Path(os.environ.get("DATA_DIR", "/data")) / "run" / "build.lock"


def acquire_build_lease(*, blocking: bool) -> BuildLease | None:
  """Acquire the shared build lease, or return None when not blocking."""
  path = build_lease_path()
  path.parent.mkdir(parents=True, exist_ok=True)
  handle = path.open("a+", encoding="utf-8")
  operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
  try:
    fcntl.flock(handle, operation)
  except BlockingIOError:
    handle.close()
    return None
  return BuildLease(handle)
