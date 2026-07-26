"""Recognize Memory-app recall lookups so a turn can cite what it remembered.

The Memory app is an ordinary installed app: the agent consults it by running
``memory_search.py`` through Bash, and the notes it read come back as ordinary
tool output. Without this module that lookup is indistinguishable from any
other shell command, so the owner cannot tell "it remembered something" from
"it ran housekeeping" — nor, more importantly, "it looked and found nothing"
from "it never looked".

Detection is deliberately two-phase and keyed off the tool's own lifecycle
rather than the shape of its output:

* ``recall_from_command`` matches the *command being run*. This is the only
  positive identification; nothing here ever concludes "this was a memory
  lookup" from output text alone, so an unrelated command that happens to
  print ``FILES:`` can never mint a citation.
* ``recall_from_output`` is then trusted to parse that command's stdout, and is
  only ever called for a tool already identified by the first phase.

The stdout contract belongs to the Memory app (``memory_search.py``'s
``retrieve``/``run``) and is stable::

    Relevant memories:
    - <title>: <excerpt> [<relative/path.md>]
    - <title>: <excerpt> [<relative/path.md>]
    FILES: notes/a.md, notes/b.md

or, for a lookup that matched nothing::

    No relevant memories.

``FILES:`` is authoritative: those paths were opened by confined Python after
the graph commit was pinned, whereas the ``- title: excerpt [path]`` lines are
presentation. So paths come from ``FILES:`` and the section lines only enrich
them with a title and excerpt. That split also makes the parse robust to the
head+tail carving a large tool output receives (``events.py``
``excerpt_tool_output``): both markers sit at the very start and very end of
the stream, so a carved middle costs some titles but never the citation set.

Every failure mode degrades to *less* metadata, never to a wrong citation:
an unparseable body still yields a bounded "hit" with path-derived titles, and
a missing command summary yields no recall at all.
"""

from __future__ import annotations

import re

# Recall metadata rides inline on the SSE event, the persisted tool block, and
# the compacted activity summary — the same budget the web-source citations
# live within. memory_search.py itself returns at most 6 files with 900-char
# excerpts; these ceilings leave headroom without letting a malformed or
# hostile stdout inflate every transcript read.
MAX_RECALL_NOTES = 12
MAX_RECALL_TITLE_CHARS = 120
MAX_RECALL_EXCERPT_CHARS = 300
MAX_RECALL_PATH_CHARS = 256
_MAX_OUTPUT_SCAN_CHARS = 262_144
_MAX_SECTION_LINES_SCANNED = 256

RECALL_SEARCHING = "searching"
RECALL_HIT = "hit"
RECALL_EMPTY = "empty"

# The command summary the backend builds for Bash is the verbatim command
# string, so identification means answering "did this command RUN the search
# script?" — not "does this command mention it?". Substring matching gets that
# wrong in the most ordinary way possible: `grep -rn memory_search.py …` and
# `cat memory_search.py` both name the script while doing something else
# entirely, and either would mint a citation from unrelated output.
#
# So the command is split into segments and each segment's HEAD is inspected:
# a lookup is either the script executed directly or an interpreter invoked on
# it. Anything where the script is a mere argument is correctly ignored.
_MAX_COMMAND_SCAN_CHARS = 8192
_SEGMENT_RE = re.compile(r"[;&|\n]+")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_INTERPRETER_RE = re.compile(r"^(?:.*/)?python[0-9.]*$")
_SCRIPT_RE = re.compile(r"^(?:.*/)?memory_search\.py$")

_EMPTY_RE = re.compile(r"^No relevant memories\.\s*$", re.MULTILINE)
_FILES_RE = re.compile(r"^FILES:[ \t]*(.+)$", re.MULTILINE)
# "- <title>: <excerpt> [<path>]" — the excerpt is greedy-free and the path is
# anchored to the end of the line, matching how memory_search.py builds it.
_SECTION_RE = re.compile(r"^- (.*?): (.*) \[([^\]]+)\]$", re.MULTILINE)

# A citation path is only ever a repository-relative markdown pointer. Refusing
# anything else keeps traversal, absolute paths, and control characters out of
# a value the client turns into a deep link.
_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*\.md$")


def _clean(value: str, limit: int) -> str:
  """Collapse whitespace and bound a label taken from tool output."""
  if not isinstance(value, str):
    return ""
  # Slice before normalizing so a pathological line cannot allocate another
  # full-size string merely to produce a short label.
  return re.sub(r"\s+", " ", value[: limit * 2]).strip()[:limit]


def _note_id(path: str) -> str:
  """The graph node id for a citation path: its file stem."""
  tail = path.rsplit("/", 1)[-1]
  return tail[:-3] if tail.endswith(".md") else tail


def _title_from_path(path: str) -> str:
  """A readable fallback when the titled section line was carved away."""
  return _note_id(path).replace("-", " ").replace("_", " ").strip()


def _safe_path(value: str) -> str:
  if not isinstance(value, str):
    return ""
  candidate = value.strip()
  if not candidate or len(candidate) > MAX_RECALL_PATH_CHARS:
    return ""
  if ".." in candidate or candidate.startswith("/"):
    return ""
  return candidate if _PATH_RE.match(candidate) else ""


def _segment_runs_search(segment: str) -> bool:
  """Whether one command segment EXECUTES the memory search script."""
  tokens = [token.strip("'\"") for token in segment.split()]
  tokens = [token for token in tokens if token]
  # `FOO=bar python3 script.py` — leading environment assignments are not the
  # command being run.
  index = 0
  while index < len(tokens) and _ENV_ASSIGN_RE.match(tokens[index]):
    index += 1
  if index >= len(tokens):
    return False
  head = tokens[index]
  if _SCRIPT_RE.match(head):
    return True
  if not _INTERPRETER_RE.match(head):
    return False
  # `python3 -u script.py` — interpreter flags may precede the script, but the
  # first non-flag token is the thing actually being run.
  for token in tokens[index + 1:]:
    if token.startswith("-"):
      continue
    return bool(_SCRIPT_RE.match(token))
  return False


def recall_from_command(command: object) -> dict | None:
  """Return a pending recall marker when this command RUNS a memory lookup.

  Called at tool-input time so the live turn can name what it is doing while
  the lookup is still in flight. Returning ``None`` means "not a memory
  lookup", which is also the safe answer for a missing or oversized command
  summary — and, deliberately, for any command that merely names the script.
  """
  if not isinstance(command, str) or not command:
    return None
  if len(command) > _MAX_COMMAND_SCAN_CHARS:
    return None
  # Cheap reject before tokenizing: the overwhelming majority of commands are
  # not memory lookups and should cost one substring scan.
  if "memory_search.py" not in command:
    return None
  for segment in _SEGMENT_RE.split(command):
    if _segment_runs_search(segment):
      return {"status": RECALL_SEARCHING}
  return None


def recall_from_output(text: object) -> dict:
  """Parse a known memory lookup's stdout into a bounded citation set.

  Only ever called for a tool ``recall_from_command`` already identified, so
  an unrecognized body is a lookup whose output we could not read — not a
  reason to claim nothing was found. That case returns a note-less ``hit``,
  which renders as a plain "recalled from Memory" beat rather than the far
  stronger (and possibly false) "nothing relevant" claim.
  """
  if not isinstance(text, str) or not text.strip():
    # No output at all: the command produced nothing readable. Keep the beat,
    # drop the claim.
    return {"status": RECALL_HIT, "notes": []}

  body = text[:_MAX_OUTPUT_SCAN_CHARS]

  files_match = None
  for files_match in _FILES_RE.finditer(body):
    # The last FILES: line wins — a head+tail carve keeps the tail, and the
    # real one is always the final line memory_search.py prints.
    pass

  if files_match is None:
    if _EMPTY_RE.search(body):
      return {"status": RECALL_EMPTY}
    return {"status": RECALL_HIT, "notes": []}

  titles: dict[str, tuple[str, str]] = {}
  for index, section in enumerate(_SECTION_RE.finditer(body)):
    if index >= _MAX_SECTION_LINES_SCANNED:
      break
    raw_title, raw_excerpt, raw_path = section.groups()
    path = _safe_path(raw_path)
    if path and path not in titles:
      titles[path] = (
        _clean(raw_title, MAX_RECALL_TITLE_CHARS),
        _clean(raw_excerpt, MAX_RECALL_EXCERPT_CHARS),
      )

  notes: list[dict[str, str]] = []
  seen: set[str] = set()
  for raw_path in files_match.group(1).split(","):
    path = _safe_path(raw_path)
    if not path or path in seen:
      continue
    seen.add(path)
    title, excerpt = titles.get(path, ("", ""))
    note = {
      "id": _note_id(path),
      "path": path,
      "title": title or _title_from_path(path) or path,
    }
    if excerpt:
      note["excerpt"] = excerpt
    notes.append(note)
    if len(notes) >= MAX_RECALL_NOTES:
      break

  # A FILES: line whose every entry failed validation is a malformed citation
  # set, not an empty lookup — same conservative fallback as an unreadable body.
  return {"status": RECALL_HIT, "notes": notes}


def merge_recall_notes(
  target: list[dict[str, str]],
  seen: set[str],
  recall: object,
) -> None:
  """Accumulate one block's notes into a deduped, bounded citation list.

  Shared by the transcript compaction rollup so the projection and the live
  block agree on ordering (first occurrence owns the position) and on the cap.
  """
  if not isinstance(recall, dict):
    return
  for note in recall.get("notes") or []:
    if not isinstance(note, dict):
      continue
    path = note.get("path")
    if not isinstance(path, str) or not path or path in seen:
      continue
    seen.add(path)
    target.append(note)
    if len(target) >= MAX_RECALL_NOTES:
      return
