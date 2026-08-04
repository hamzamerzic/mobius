"""Resource-aware admission for optional raster preview generation."""

from PIL import Image

import app.image_previews as previews


def _source(path):
  Image.new("RGB", (1600, 900), (40, 80, 120)).save(path, "PNG")


def _unexpected(message):
  def fail(*_args, **_kwargs):
    raise AssertionError(message)
  return fail


def test_uncached_preview_skips_decode_under_memory_pressure(
  tmp_path, monkeypatch,
):
  source = tmp_path / "large.png"
  _source(source)
  monkeypatch.setattr(
    previews,
    "assess_memory_pressure",
    lambda: {"state": "constrained", "headroom_bytes": 128 * 1024**2},
  )
  monkeypatch.setattr(
    previews.Image,
    "open",
    _unexpected("pressure-gated preview must not decode the source"),
  )

  assert previews.display_image_preview(source, tmp_path) is None
  assert not previews.preview_cache_path(source, tmp_path).exists()


def test_preview_rechecks_pressure_after_waiting_for_generation_slot(
  tmp_path, monkeypatch,
):
  source = tmp_path / "queued.png"
  _source(source)
  state = {"value": "normal"}

  class PressureRaisingSlot:
    def __enter__(self):
      state["value"] = "critical"

    def __exit__(self, *_exc):
      return None

  monkeypatch.setattr(previews, "_GENERATION_SLOTS", PressureRaisingSlot())
  monkeypatch.setattr(
    previews,
    "assess_memory_pressure",
    lambda: {"state": state["value"]},
  )
  monkeypatch.setattr(
    previews.Image,
    "open",
    _unexpected("queued preview must recheck pressure before decoding"),
  )

  assert previews.display_image_preview(source, tmp_path) is None


def test_fresh_cached_preview_is_returned_before_pressure_check(
  tmp_path, monkeypatch,
):
  source = tmp_path / "cached.png"
  _source(source)
  monkeypatch.setattr(
    previews,
    "assess_memory_pressure",
    lambda: {"state": "normal", "headroom_bytes": 1024 * 1024**2},
  )
  cached = previews.display_image_preview(source, tmp_path)
  assert cached is not None

  monkeypatch.setattr(
    previews,
    "assess_memory_pressure",
    _unexpected("fresh cache must not inspect memory pressure"),
  )
  monkeypatch.setattr(
    previews.Image,
    "open",
    _unexpected("fresh cache must not reopen the source"),
  )

  assert previews.display_image_preview(source, tmp_path) == cached


def test_unknown_memory_pressure_allows_normal_preview_generation(
  tmp_path, monkeypatch,
):
  source = tmp_path / "unknown.png"
  _source(source)
  monkeypatch.setattr(
    previews,
    "assess_memory_pressure",
    lambda: {"state": "unknown", "headroom_bytes": None},
  )

  generated = previews.display_image_preview(source, tmp_path)

  assert generated is not None
  assert generated.is_file()
