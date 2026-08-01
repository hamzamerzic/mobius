"""Partner-actionable failures from reviewed contribution operations."""

from __future__ import annotations

import re

# Terminal styling and stray control bytes. Colour codes are correct for a
# terminal and wrong for everything we persist or render: they survive JSON,
# reach the owner's review card as literal `[1;31m` noise, and disfigure the
# very diagnostic they were meant to highlight. Strip them at the boundary
# where command output stops being terminal output and becomes stored text.
_TERMINAL_NOISE = re.compile(
  r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"    # OSC ... BEL/ST
  r"|\x1b\[[0-9;?]*[ -/]*[@-~]"           # CSI (colour, cursor moves)
  r"|\x1b[@-Z\\-_]"                       # two-byte escapes
  r"|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"    # other control bytes
)

# Möbius's own pre-push gate prefixes every line it prints, and names each
# failing check as `[pre-push] <name> FAILED:`. Reading those two markers is a
# contract between two Möbius-owned components, not a guess about the shape of
# arbitrary hook output: anything unrecognized is reported as a remote refusal.
_LOCAL_GATE = re.compile(r"^\[pre-push\]", re.MULTILINE)
_LOCAL_GATE_CHECK = re.compile(r"^\[pre-push\]\s+(.+?)\s+FAILED\b", re.MULTILINE)

_DETAIL_LIMIT = 2000


class ContributionSubmitError(Exception):
  """A reviewed GitHub action failed without exposing unsafe raw state.

  ``message`` is the single owner-facing sentence. ``detail`` is optional
  diagnostic text for the disclosure beneath it — already sanitized, never a
  substitute for a real message, and never the thing shown first.
  """

  def __init__(
    self,
    message: str,
    status_code: int = 409,
    *,
    record_patch: dict | None = None,
    code: str | None = None,
    detail: str | None = None,
  ):
    super().__init__(message)
    self.message = message
    self.status_code = status_code
    self.record_patch = record_patch or {}
    self.code = code
    self.detail = detail or ""


def readable_output(raw: str, *, limit: int = _DETAIL_LIMIT) -> str:
  """Turn a captured command transcript into text safe to store and show.

  Keeps the TAIL when it overflows: a failing command states its reason last,
  so truncating from the front preserves the banner and discards the answer.
  """
  text = _TERMINAL_NOISE.sub("", str(raw or ""))
  lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]

  collapsed: list[str] = []
  for line in lines:
    if not line and (not collapsed or not collapsed[-1]):
      continue
    collapsed.append(line)
  while collapsed and not collapsed[-1]:
    collapsed.pop()

  cleaned = "\n".join(collapsed)
  if len(cleaned) <= limit:
    return cleaned
  kept = cleaned[-limit:]
  return "…\n" + kept.split("\n", 1)[-1]


def push_rejected(
  raw: str,
  *,
  record_patch: dict | None = None,
) -> ContributionSubmitError:
  """Explain a refused push in one sentence, with the transcript behind it.

  Git hands back whatever the transport and the local hooks printed. That is a
  developer's terminal artifact, not an owner-facing explanation, so it belongs
  in ``detail`` while ``message`` says who refused and what is true of the
  branch now — in every case, that nothing was published.
  """
  detail = readable_output(raw)

  if _LOCAL_GATE.search(detail):
    if "privacy gate" in detail:
      message = (
        "Möbius's privacy gate stopped this push: the branch still contains "
        "private workspace paths. Nothing was published."
      )
    else:
      checks = list(dict.fromkeys(_LOCAL_GATE_CHECK.findall(detail)))
      named = f" ({', '.join(checks)})" if checks else ""
      message = (
        f"This did not pass the checks Möbius runs before publishing{named}. "
        "Nothing was published — fix it locally, then send again."
      )
  elif detail:
    message = "GitHub would not accept this branch, so nothing was published."
  else:
    message = "The push failed, so nothing was published."

  return ContributionSubmitError(message, record_patch=record_patch, detail=detail)
