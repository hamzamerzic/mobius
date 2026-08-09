"""Capacity-aware observation and crash-loop retention for ``/data``.

The live platform tree and its newest crash-loop quarantine are durable owner
state.  This module keeps those invariants at the point where a second platform
tree would be admitted, while treating browser caches and older redundant
quarantines as reclaimable in that order.

Normal health reads consume a cached, bounded top-level scan.  The only exact
recursive scans are on the crash-loop path, where underestimating a clone would
be unsafe and the work happens before the live tree is moved.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


MIB = 1024 * 1024
GIB = 1024 * MIB
_STATUS_RELATIVE = Path("run/data-volume-status.json")
_RECOVERY_PREFIX = "platform.crashloop-prev."
_DEFAULT_BREAKDOWN_SECONDS = 2.0
_DEFAULT_BREAKDOWN_ENTRIES = 200_000
_DEFAULT_TOP_LEVEL_ENTRIES = 256


def _allocated_bytes(stat_result: os.stat_result) -> int:
  blocks = getattr(stat_result, "st_blocks", None)
  if blocks is not None:
    return int(blocks) * 512
  return int(stat_result.st_size)


def _raise_walk_error(error: OSError) -> None:
  raise error


def _tree_allocated_bytes(
  path: Path,
  *,
  deadline: float | None = None,
  remaining_entries: list[int] | None = None,
) -> tuple[int, bool]:
  """Count allocated bytes exactly, or return a bounded lower estimate."""
  def exhausted() -> bool:
    return (
      (deadline is not None and time.monotonic() >= deadline)
      or (remaining_entries is not None and remaining_entries[0] <= 0)
    )

  total = _allocated_bytes(path.lstat())
  if remaining_entries is not None:
    remaining_entries[0] -= 1
  if path.is_symlink() or not path.is_dir():
    return total, True
  for current, dirnames, filenames in os.walk(
    path, followlinks=False, onerror=_raise_walk_error,
  ):
    if exhausted():
      return total, False
    current_path = Path(current)
    kept_dirs = []
    for name in dirnames:
      if exhausted():
        return total, False
      child = current_path / name
      total += _allocated_bytes(child.lstat())
      if remaining_entries is not None:
        remaining_entries[0] -= 1
      if not child.is_symlink():
        kept_dirs.append(name)
    dirnames[:] = kept_dirs
    for name in filenames:
      if exhausted():
        return total, False
      total += _allocated_bytes((current_path / name).lstat())
      if remaining_entries is not None:
        remaining_entries[0] -= 1
  return total, True


def exact_tree_allocated_bytes(path: str | Path) -> int:
  """Return allocated bytes without following symlinks; fail on unreadable data."""
  total, _complete = _tree_allocated_bytes(Path(path))
  return total


def _disk_dict(data_dir: Path, disk_usage: Callable = shutil.disk_usage) -> dict:
  usage = disk_usage(data_dir)
  return {
    "path": str(data_dir),
    "total_bytes": int(usage.total),
    "used_bytes": int(usage.used),
    "free_bytes": int(usage.free),
  }


def data_volume_snapshot(
  data_dir: str | Path,
  *,
  disk_usage: Callable = shutil.disk_usage,
  time_budget_seconds: float = _DEFAULT_BREAKDOWN_SECONDS,
  entry_budget: int = _DEFAULT_BREAKDOWN_ENTRIES,
  top_level_budget: int = _DEFAULT_TOP_LEVEL_ENTRIES,
) -> dict[str, Any]:
  """Capture capacity plus a bounded top-level allocated-byte breakdown."""
  root = Path(data_dir)
  deadline = time.monotonic() + max(0.01, time_budget_seconds)
  remaining_entries = max(1, entry_budget)
  entries = []
  complete = True
  try:
    children = sorted(root.iterdir(), key=lambda child: child.name)
  except OSError:
    children = []
    complete = False
  omitted_top_level = max(0, len(children) - top_level_budget)
  children = children[:top_level_budget]
  complete = complete and omitted_top_level == 0
  for index, child in enumerate(children):
    now = time.monotonic()
    if now >= deadline or remaining_entries <= 0:
      complete = False
      entries.extend({
        "name": pending.name,
        "bytes": None,
        "complete": False,
      } for pending in children[index:])
      break
    remaining_children = len(children) - index
    child_entry_budget = max(1, remaining_entries // remaining_children)
    child_entries = [child_entry_budget]
    child_deadline = min(
      deadline,
      now + max(0.005, (deadline - now) / remaining_children),
    )
    try:
      size, child_complete = _tree_allocated_bytes(
        child,
        deadline=child_deadline,
        remaining_entries=child_entries,
      )
    except OSError:
      size, child_complete = None, False
    remaining_entries -= child_entry_budget - max(0, child_entries[0])
    entries.append({
      "name": child.name,
      "bytes": size,
      "complete": child_complete,
    })
    complete = complete and child_complete
  entries.sort(key=lambda entry: (
    entry["bytes"] is None,
    -(entry["bytes"] or 0),
    entry["name"],
  ))
  return {
    "captured_at": datetime.now(UTC).isoformat(),
    "capacity": _disk_dict(root, disk_usage),
    "top_level": {
      "entries": entries,
      "complete": complete,
      "entry_budget": entry_budget,
      "top_level_budget": top_level_budget,
      "omitted_top_level": omitted_top_level,
      "time_budget_seconds": time_budget_seconds,
    },
  }


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
  temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
  temp.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
  os.replace(temp, path)


def _status_path(data_dir: str | Path) -> Path:
  return Path(data_dir) / _STATUS_RELATIVE


def refresh_data_volume_status(data_dir: str | Path) -> dict[str, Any]:
  snapshot = data_volume_snapshot(data_dir)
  previous = read_data_volume_status(data_dir)
  if previous is not None:
    for key in ("last_crashloop_admission", "last_crashloop_retention"):
      if key in previous:
        snapshot[key] = previous[key]
  _write_json_atomic(_status_path(data_dir), snapshot)
  return snapshot


def read_data_volume_status(data_dir: str | Path) -> dict[str, Any] | None:
  try:
    value = json.loads(
      _status_path(data_dir).read_text(encoding="utf-8"),
    )
  except (OSError, json.JSONDecodeError):
    return None
  if not isinstance(value, dict) or not isinstance(value.get("top_level"), dict):
    return None
  return value


def _record_status(data_dir: str | Path, key: str, value: dict[str, Any]) -> None:
  status = refresh_data_volume_status(data_dir)
  status[key] = value
  _write_json_atomic(_status_path(data_dir), status)


def _env_bytes(name: str, default: int) -> int:
  try:
    value = int(os.environ.get(name, str(default)))
  except ValueError:
    return default
  return value if value >= 0 else default


def _reserve_bytes(total_bytes: int) -> int:
  default = min(total_bytes, max(32 * MIB, int(total_bytes * 0.05)), GIB)
  return _env_bytes("MOBIUS_DATA_VOLUME_RESERVE_BYTES", default)


def _recovery_budget_bytes(total_bytes: int) -> int:
  default = min(2 * GIB, total_bytes // 4)
  return _env_bytes("MOBIUS_CRASHLOOP_RECOVERY_MAX_BYTES", default)


def _clone_estimate_bytes(
  primary_bytes: int,
  clone_source_dir: str | Path | None,
  tree_size: Callable[[Path], int],
) -> int:
  estimate = primary_bytes
  if clone_source_dir is not None:
    source = Path(clone_source_dir)
    if source.is_dir():
      estimate = max(estimate, tree_size(source))
  # An override may reserve more for unusual remotes, never less than either
  # concrete tree available at admission time.
  return max(
    estimate,
    _env_bytes("MOBIUS_PLATFORM_CLONE_ESTIMATE_BYTES", estimate),
  )


def _recovery_points(data_dir: Path) -> list[Path]:
  points = [
    path for path in data_dir.glob(f"{_RECOVERY_PREFIX}*")
    if path.is_dir() and not path.is_symlink()
  ]
  # The UTC timestamp in the quarantine name is immutable creation identity;
  # directory mtimes change when an owner inspects or repairs preserved files.
  return sorted(points, key=lambda path: path.name, reverse=True)


def _prune_recovery_history(
  data_dir: Path,
  *,
  required_free_bytes: int,
  budget_bytes: int,
  disk_usage: Callable = shutil.disk_usage,
  tree_size: Callable[[Path], int] = exact_tree_allocated_bytes,
  remove_tree: Callable[[Path], None] = shutil.rmtree,
) -> dict[str, Any]:
  points = _recovery_points(data_dir)
  sizes: dict[Path, int] = {}
  errors = []
  for path in points:
    try:
      sizes[path] = tree_size(path)
    except OSError as exc:
      errors.append(f"could not size {path.name}: {exc}")
  retained_bytes = sum(sizes.values())
  pruned = []
  # The newest point is never a candidate. Older points yield oldest-first so
  # the most recent redundant history survives when capacity permits.
  for path in reversed(points[1:]):
    free_bytes = int(disk_usage(data_dir).free)
    if free_bytes >= required_free_bytes and retained_bytes <= budget_bytes:
      break
    if path not in sizes:
      continue
    try:
      remove_tree(path)
    except OSError as exc:
      errors.append(f"could not prune {path.name}: {exc}")
      continue
    retained_bytes = max(0, retained_bytes - sizes[path])
    pruned.append({"name": path.name, "bytes": sizes[path]})
  return {
    "newest_preserved": points[0].name if points else None,
    "pruned": pruned,
    "retained_bytes": retained_bytes,
    "budget_bytes": budget_bytes,
    "errors": errors,
    "free_bytes": int(disk_usage(data_dir).free),
  }


def admit_crashloop_reclone(
  data_dir: str | Path,
  platform_dir: str | Path,
  *,
  disk_usage: Callable = shutil.disk_usage,
  tree_size: Callable[[Path], int] = exact_tree_allocated_bytes,
  cache_reclaimer: Callable[[Path], dict[str, Any]] | None = None,
  remove_tree: Callable[[Path], None] = shutil.rmtree,
  clone_source_dir: str | Path | None = None,
) -> dict[str, Any]:
  """Reclaim safe bytes and decide before the live platform tree is moved."""
  root = Path(data_dir)
  platform = Path(platform_dir)
  usage = disk_usage(root)
  total_bytes = int(usage.total)
  reserve_bytes = _reserve_bytes(total_bytes)
  try:
    platform_bytes = tree_size(platform)
  except OSError as exc:
    return {
      "admitted": False,
      "reason": f"live platform tree could not be sized: {exc}",
      "free_bytes": int(usage.free),
    }
  try:
    clone_estimate = _clone_estimate_bytes(
      platform_bytes, clone_source_dir, tree_size,
    )
  except OSError as exc:
    return {
      "admitted": False,
      "reason": f"baked clone source could not be sized: {exc}",
      "free_bytes": int(usage.free),
    }
  required_free = clone_estimate + reserve_bytes
  cache_result: dict[str, Any] = {"reclaimed_bytes": 0}
  if int(usage.free) < required_free:
    try:
      if cache_reclaimer is None:
        from app.browser_profiles import enforce_browser_profile_quota
        cache_result = enforce_browser_profile_quota(
          root,
          {},
          set(),
          max_bytes=0,
          low_water_bytes=0,
          cache_only=True,
        )
      else:
        cache_result = cache_reclaimer(root)
    except Exception as exc:  # Admission continues to older redundant history.
      cache_result = {"reclaimed_bytes": 0, "error": str(exc)}

  recovery = _prune_recovery_history(
    root,
    required_free_bytes=required_free,
    budget_bytes=_recovery_budget_bytes(total_bytes),
    disk_usage=disk_usage,
    tree_size=tree_size,
    remove_tree=remove_tree,
  )
  free_bytes = int(disk_usage(root).free)
  # Every currently retained point becomes older history after the atomic move
  # installs the current live tree as the new newest recovery. Admission may
  # therefore rely on those bytes, but does not delete them early; the post-move
  # check below must actually reclaim them before bootstrap can clone.
  post_move_free_bytes = free_bytes + int(recovery["retained_bytes"])
  admitted = free_bytes >= required_free or post_move_free_bytes >= required_free
  return {
    "admitted": admitted,
    "reason": None if admitted else "insufficient free space for a second platform tree",
    "volume_total_bytes": total_bytes,
    "free_bytes": free_bytes,
    "platform_bytes": platform_bytes,
    "clone_estimate_bytes": clone_estimate,
    "reserve_bytes": reserve_bytes,
    "required_free_bytes": required_free,
    "post_move_free_bytes": post_move_free_bytes,
    "post_move_prune_required": free_bytes < required_free,
    "browser_cache": cache_result,
    "recovery": recovery,
  }


def record_crashloop_quarantine(
  data_dir: str | Path,
  *,
  disk_usage: Callable = shutil.disk_usage,
  tree_size: Callable[[Path], int] = exact_tree_allocated_bytes,
  remove_tree: Callable[[Path], None] = shutil.rmtree,
  clone_source_dir: str | Path | None = None,
) -> dict[str, Any]:
  """Apply the byte budget after a new quarantine becomes the newest point."""
  root = Path(data_dir)
  usage = disk_usage(root)
  points = _recovery_points(root)
  if not points:
    return {
      "newest_preserved": None,
      "pruned": [],
      "retained_bytes": 0,
      "budget_bytes": _recovery_budget_bytes(int(usage.total)),
      "free_bytes": int(usage.free),
      "required_free_bytes": None,
      # No recovery means a bootstrap would create the only platform tree; the
      # second-tree admission policy has nothing to protect or budget here.
      "ready_for_clone": True,
      "errors": [],
    }
  try:
    newest_bytes = tree_size(points[0])
    clone_estimate = _clone_estimate_bytes(
      newest_bytes, clone_source_dir, tree_size,
    )
  except OSError as exc:
    return {
      "newest_preserved": points[0].name,
      "pruned": [],
      "retained_bytes": 0,
      "budget_bytes": _recovery_budget_bytes(int(usage.total)),
      "free_bytes": int(usage.free),
      "required_free_bytes": None,
      "ready_for_clone": False,
      "errors": [f"could not size clone inputs: {exc}"],
    }
  required_free = clone_estimate + _reserve_bytes(int(usage.total))
  result = _prune_recovery_history(
    root,
    required_free_bytes=required_free,
    budget_bytes=_recovery_budget_bytes(int(usage.total)),
    disk_usage=disk_usage,
    tree_size=tree_size,
    remove_tree=remove_tree,
  )
  result["required_free_bytes"] = required_free
  result["ready_for_clone"] = (
    result["free_bytes"] >= required_free and not result["errors"]
  )
  return result


def _parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description=__doc__)
  subparsers = parser.add_subparsers(dest="command", required=True)
  for command in ("admit-crashloop", "record-crashloop", "snapshot"):
    child = subparsers.add_parser(command)
    child.add_argument("--data-dir", default="/data")
    if command in ("admit-crashloop", "record-crashloop"):
      child.add_argument("--clone-source-dir", default="/app/platform-baked")
    if command == "admit-crashloop":
      child.add_argument("--platform-dir", default="/data/platform")
  return parser


def main(argv: list[str] | None = None) -> int:
  args = _parser().parse_args(argv)
  if args.command == "admit-crashloop":
    result = admit_crashloop_reclone(
      args.data_dir,
      args.platform_dir,
      clone_source_dir=args.clone_source_dir,
    )
    try:
      _record_status(args.data_dir, "last_crashloop_admission", result)
    except OSError as exc:
      result["status_error"] = str(exc)
    print(json.dumps(result, sort_keys=True), file=sys.stderr)
    return 0 if result["admitted"] else 75
  if args.command == "record-crashloop":
    result = record_crashloop_quarantine(
      args.data_dir,
      clone_source_dir=args.clone_source_dir,
    )
    try:
      _record_status(args.data_dir, "last_crashloop_retention", result)
    except OSError as exc:
      result["status_error"] = str(exc)
  else:
    result = refresh_data_volume_status(args.data_dir)
  print(json.dumps(result, sort_keys=True), file=sys.stderr)
  if args.command == "record-crashloop":
    return 0 if result.get("ready_for_clone") else 75
  return 1 if result.get("errors") else 0


if __name__ == "__main__":
  raise SystemExit(main())
