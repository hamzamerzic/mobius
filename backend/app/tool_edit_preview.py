"""Build bounded unified-diff previews for provider edit tools."""

from __future__ import annotations

import difflib
import json
from typing import Any


# Edit previews live inline with the tool block so they are immediately
# available when its disclosure opens. Keep that durable payload comparable to
# the ordinary bounded tool-output preview rather than copying whole files into
# every transcript.
MAX_EDIT_PREVIEW_CHARS = 20_000


def _bounded_preview(diff: str, *, relative: bool = False) -> dict | None:
  if not diff:
    return None
  truncated = len(diff) > MAX_EDIT_PREVIEW_CHARS
  return {
    "diff": diff[:MAX_EDIT_PREVIEW_CHARS],
    "truncated": truncated,
    **({"relative": True} if relative else {}),
  }


def _quoted_path(path: str) -> str:
  if any(char.isspace() or char in {'"', "\\"} for char in path):
    return json.dumps(path, ensure_ascii=False)
  return path


def _git_path(side: str, path: str) -> str:
  # Absolute paths intentionally become a//data/...; the canonical parser
  # removes the a/ or b/ side and preserves the leading slash.
  return _quoted_path(f"{side}/{path}")


def _selection_hunk(edit: dict[str, Any]) -> list[str]:
  old = edit.get("old_string")
  new = edit.get("new_string")
  if not isinstance(old, str) or not isinstance(new, str):
    return []
  # Discard the ---/+++ headers: every selection belongs to the one file entry
  # declared by claude_edit_preview, while each @@ section remains independent.
  return list(difflib.unified_diff(
    old.splitlines(), new.splitlines(), lineterm="",
  ))[2:]


def claude_edit_preview(tool: str, inp: Any) -> dict | None:
  """Build an honest selection-relative preview from Claude edit arguments."""
  if not isinstance(inp, dict) or tool not in {"Edit", "MultiEdit"}:
    return None
  path = inp.get("file_path")
  if not isinstance(path, str) or not path:
    return None
  raw_edits = inp.get("edits") if tool == "MultiEdit" else [inp]
  edits = raw_edits if isinstance(raw_edits, list) else []
  hunks = [
    line
    for edit in edits if isinstance(edit, dict)
    for line in _selection_hunk(edit)
  ]
  if not hunks:
    return None
  header = [
    "diff --git "
    f"{_git_path('a', path)} {_git_path('b', path)}",
    f"--- {_git_path('a', path)}",
    f"+++ {_git_path('b', path)}",
  ]
  return _bounded_preview("\n".join([*header, *hunks]), relative=True)


def codex_edit_preview(changes: Any) -> dict | None:
  """Build a unified preview from Codex FileUpdateChange dictionaries."""
  if not isinstance(changes, list):
    return None
  sections: list[str] = []
  for change in changes:
    if not isinstance(change, dict):
      continue
    path = change.get("path")
    patch = change.get("diff")
    if not isinstance(path, str) or not path or not isinstance(patch, str):
      continue
    if patch.startswith("diff --git "):
      sections.append(patch)
      continue
    raw_kind = change.get("kind")
    kind = raw_kind if isinstance(raw_kind, dict) else {}
    kind_type = str(kind.get("type") or "update")
    move_path = kind.get("move_path")
    new_path = move_path if isinstance(move_path, str) and move_path else path
    header = [
      "diff --git "
      f"{_git_path('a', path)} {_git_path('b', new_path)}",
    ]
    if kind_type == "add":
      header.extend([
        "new file mode 100644",
        "--- /dev/null",
        f"+++ {_git_path('b', new_path)}",
      ])
    elif kind_type == "delete":
      header.extend([
        "deleted file mode 100644",
        f"--- {_git_path('a', path)}",
        "+++ /dev/null",
      ])
    else:
      if new_path != path:
        header.extend([
          f"rename from {_quoted_path(path)}",
          f"rename to {_quoted_path(new_path)}",
        ])
      header.extend([
        f"--- {_git_path('a', path)}",
        f"+++ {_git_path('b', new_path)}",
      ])
    sections.append("\n".join([*header, patch]))
  return _bounded_preview("\n".join(sections))
