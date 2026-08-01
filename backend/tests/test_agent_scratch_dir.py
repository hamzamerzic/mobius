"""Agent scratch is pinned to the bounded data volume, not the container /tmp.

The container root is an overlay: its upperdir lives on the host filesystem,
has no size of its own, and carries no quota. `df` inside the container
therefore reports HOST capacity for /tmp, and scratch written there spends
host disk the platform can neither bound nor measure. On 2026-08-01 that had
accumulated 4.5 GiB — /tmp is not a tmpfs in this image, so it also survives
every restart instead of being cleared.
"""

from pathlib import Path

from app import config


def _pin_data_dir(monkeypatch, tmp_path: Path) -> Path:
  monkeypatch.setattr(
    config, "get_settings", lambda: type("S", (), {"data_dir": str(tmp_path)})()
  )
  return tmp_path


def test_agent_scratch_dir_lives_on_the_data_volume_not_container_tmp(
  monkeypatch, tmp_path
):
  """Derived from data_dir rather than the process temp dir. Asserting the
  absence of a literal '/tmp' prefix would prove nothing — pytest's own
  tmp_path lives under /tmp — so the contract under test is that the scratch
  path tracks the configured volume wherever that volume is."""
  data_dir = _pin_data_dir(monkeypatch, tmp_path)

  scratch = config.agent_scratch_dir()

  assert scratch == data_dir / "tmp"
  assert data_dir in scratch.parents


def test_agent_scratch_dir_follows_the_configured_volume(monkeypatch, tmp_path):
  """A hardcoded path would still satisfy a single-volume assertion, so move
  the volume and require the scratch dir to move with it."""
  first_volume = _pin_data_dir(monkeypatch, tmp_path / "volume-a")
  first = config.agent_scratch_dir()

  second_volume = _pin_data_dir(monkeypatch, tmp_path / "volume-b")
  second = config.agent_scratch_dir()

  assert first != second
  assert first_volume in first.parents
  assert second_volume in second.parents


def test_agent_scratch_dir_is_usable_on_first_call(monkeypatch, tmp_path):
  """Callers export this straight into a subprocess environment, so it has to
  exist before that process starts rather than on first write."""
  _pin_data_dir(monkeypatch, tmp_path)

  scratch = config.agent_scratch_dir()

  assert scratch.is_dir()


def test_agent_scratch_dir_tolerates_an_existing_directory(monkeypatch, tmp_path):
  """Every chat turn calls this; the second turn must not fail on the
  directory its predecessor created."""
  _pin_data_dir(monkeypatch, tmp_path)

  first = config.agent_scratch_dir()
  (first / "leftover.txt").write_text("from an earlier turn")

  second = config.agent_scratch_dir()

  assert second == first
  assert (second / "leftover.txt").read_text() == "from an earlier turn"
