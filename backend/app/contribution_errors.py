"""Partner-actionable failures from reviewed contribution operations."""

from __future__ import annotations


class ContributionSubmitError(Exception):
  """A reviewed GitHub action failed without exposing unsafe raw state."""

  def __init__(
    self,
    message: str,
    status_code: int = 409,
    *,
    record_patch: dict | None = None,
    code: str | None = None,
  ):
    super().__init__(message)
    self.message = message
    self.status_code = status_code
    self.record_patch = record_patch or {}
    self.code = code
