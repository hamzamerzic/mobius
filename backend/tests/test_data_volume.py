"""Volume-capacity policy stays non-destructive under Trial-sized pressure."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

from app.data_volume import (
  MIB,
  admit_crashloop_reclone,
  data_volume_snapshot,
  read_data_volume_status,
  record_crashloop_quarantine,
  refresh_data_volume_status,
)


def _point(root: Path, name: str, *, mtime: int) -> Path:
  point = root / name
  point.mkdir()
  (point / "owner-edit.txt").write_text(name)
  os.utime(point, (mtime, mtime))
  return point


def test_trial_volume_reclaims_cache_then_old_redundant_recovery(
  tmp_path,
):
  total = 512 * MIB
  platform = tmp_path / "platform"
  platform.mkdir()
  recovery = _point(
    tmp_path, "platform.crashloop-prev.20260809T020000Z", mtime=2,
  )
  cache_reclaimed = False
  actions = []

  def disk_usage(_path):
    free = 33 * MIB
    if cache_reclaimed:
      free += 95 * MIB
    if not recovery.exists():
      free += 95 * MIB
    return SimpleNamespace(total=total, used=total - free, free=free)

  sizes = {
    "platform": 133 * MIB,
    recovery.name: 95 * MIB,
  }

  def reclaim(_root):
    nonlocal cache_reclaimed
    cache_reclaimed = True
    actions.append("browser-cache")
    return {"reclaimed_bytes": 95 * MIB}

  def remove(path):
    actions.append(path.name)
    shutil.rmtree(path)

  result = admit_crashloop_reclone(
    tmp_path,
    platform,
    disk_usage=disk_usage,
    tree_size=lambda path: sizes[path.name],
    cache_reclaimer=reclaim,
    remove_tree=remove,
  )

  assert result["admitted"] is True
  assert result["required_free_bytes"] == 165 * MIB
  assert result["post_move_prune_required"] is True
  assert actions == ["browser-cache"]
  assert recovery.exists()
  assert platform.exists(), "admission must not move the live tree"

  newest = tmp_path / "platform.crashloop-prev.20260809T030000Z"
  platform.rename(newest)
  sizes[newest.name] = 133 * MIB
  retention = record_crashloop_quarantine(
    tmp_path,
    disk_usage=disk_usage,
    tree_size=lambda path: sizes[path.name],
    remove_tree=remove,
  )

  assert retention["ready_for_clone"] is True
  assert actions == ["browser-cache", recovery.name]
  assert newest.exists()
  assert not recovery.exists()


def test_admission_fails_before_touching_live_or_only_recovery(tmp_path):
  total = 512 * MIB
  platform = tmp_path / "platform"
  platform.mkdir()
  newest = _point(
    tmp_path, "platform.crashloop-prev.20260809T020000Z", mtime=2,
  )
  cache_reclaimed = False

  def disk_usage(_path):
    free = 20 * MIB + (10 * MIB if cache_reclaimed else 0)
    return SimpleNamespace(total=total, used=total - free, free=free)

  def reclaim(_root):
    nonlocal cache_reclaimed
    cache_reclaimed = True
    return {"reclaimed_bytes": 10 * MIB}

  result = admit_crashloop_reclone(
    tmp_path,
    platform,
    disk_usage=disk_usage,
    tree_size=lambda path: 133 * MIB if path == platform else 95 * MIB,
    cache_reclaimer=reclaim,
  )

  assert result["admitted"] is False
  assert platform.exists()
  assert newest.exists()
  assert result["recovery"]["pruned"] == []


def test_admission_sizes_the_larger_baked_clone_source(monkeypatch, tmp_path):
  platform = tmp_path / "platform"
  platform.mkdir()
  baked = tmp_path / "platform-baked"
  baked.mkdir()
  monkeypatch.setenv("MOBIUS_PLATFORM_CLONE_ESTIMATE_BYTES", "1")

  result = admit_crashloop_reclone(
    tmp_path,
    platform,
    clone_source_dir=baked,
    disk_usage=lambda _path: SimpleNamespace(
      total=512 * MIB, used=352 * MIB, free=160 * MIB,
    ),
    tree_size=lambda path: 100 * MIB if path == platform else 140 * MIB,
    cache_reclaimer=lambda _root: {"reclaimed_bytes": 0},
  )

  assert result["clone_estimate_bytes"] == 140 * MIB
  assert result["required_free_bytes"] == 172 * MIB
  assert result["admitted"] is False


def test_newest_recovery_preserves_files_modes_and_symlinks(
  monkeypatch, tmp_path,
):
  older = _point(
    tmp_path, "platform.crashloop-prev.20260809T010000Z", mtime=3,
  )
  platform = tmp_path / "platform"
  platform.mkdir()
  owner_edit = platform / "owner-edit.txt"
  owner_edit.write_text("committed")
  subprocess.run(["git", "-C", str(platform), "init", "-q"], check=True)
  subprocess.run(
    ["git", "-C", str(platform), "config", "user.name", "Test Owner"],
    check=True,
  )
  subprocess.run(
    ["git", "-C", str(platform), "config", "user.email", "owner@example.test"],
    check=True,
  )
  subprocess.run(["git", "-C", str(platform), "add", "."], check=True)
  subprocess.run(
    ["git", "-C", str(platform), "commit", "-qm", "owner commit"],
    check=True,
  )
  owner_edit.write_text("dirty tracked edit")
  (platform / "untracked.txt").write_text("untracked owner work")
  executable = platform / "local-tool"
  executable.write_text("#!/bin/sh\nexit 0\n")
  executable.chmod(0o755)
  (platform / "local-link").symlink_to("owner-edit.txt")
  newest = tmp_path / "platform.crashloop-prev.20260809T020000Z"
  platform.rename(newest)
  monkeypatch.setenv("MOBIUS_CRASHLOOP_RECOVERY_MAX_BYTES", "0")

  result = record_crashloop_quarantine(tmp_path)

  assert result["newest_preserved"] == newest.name
  assert not older.exists()
  assert (newest / "owner-edit.txt").read_text() == "dirty tracked edit"
  assert (newest / "untracked.txt").read_text() == "untracked owner work"
  assert (newest / "local-link").is_symlink()
  assert os.access(newest / executable.name, os.X_OK)
  assert subprocess.check_output(
    ["git", "-C", str(newest), "rev-list", "--count", "HEAD"], text=True,
  ).strip() == "1"
  status = subprocess.check_output(
    ["git", "-C", str(newest), "status", "--porcelain"], text=True,
  )
  assert " M owner-edit.txt" in status
  assert "?? untracked.txt" in status


def test_status_scan_is_bounded_and_round_trips(tmp_path):
  (tmp_path / "run").mkdir()
  (tmp_path / "platform").mkdir()
  (tmp_path / "platform" / "a").write_bytes(b"a" * 4096)
  (tmp_path / "db").mkdir()
  snapshot = data_volume_snapshot(tmp_path, entry_budget=1)

  assert snapshot["capacity"]["total_bytes"] > 0
  assert snapshot["top_level"]["complete"] is False
  assert any(entry["complete"] is False for entry in snapshot["top_level"]["entries"])

  written = refresh_data_volume_status(tmp_path)
  assert read_data_volume_status(tmp_path) == written
  status_path = tmp_path / "run/data-volume-status.json"
  status = json.loads(status_path.read_text())
  status["last_crashloop_admission"] = {"admitted": False}
  status_path.write_text(json.dumps(status))
  assert refresh_data_volume_status(tmp_path)["last_crashloop_admission"] == {
    "admitted": False,
  }


def test_entrypoint_admits_before_move_and_falls_back_without_capacity():
  entrypoint = (
    Path(__file__).resolve().parents[1] / "scripts" / "entrypoint.sh"
  ).read_text(encoding="utf-8")
  admission = entrypoint.index("admit-crashloop --data-dir /data")
  move = entrypoint.index(
    'mv /data/platform "/data/platform.crashloop-prev.$_cl_ts"', admission,
  )
  selection = entrypoint.index('if [ "$_crashloop_force_baked" -eq 1 ]')

  assert admission < move < selection
  assert "tail -n +4" not in entrypoint
  assert "record-crashloop --data-dir /data" in entrypoint
  assert "_restore_capacity_ready" in entrypoint
