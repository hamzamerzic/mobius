"""Exact generated-image handoff into chat media."""

import importlib.util
from pathlib import Path

import pytest


SCRIPT = (
  Path(__file__).resolve().parents[1] / "scripts" / "publish_chat_image.py"
)


def _load():
  spec = importlib.util.spec_from_file_location("publish_chat_image", SCRIPT)
  module = importlib.util.module_from_spec(spec)
  assert spec.loader is not None
  spec.loader.exec_module(module)
  return module


def test_publish_copies_the_exact_named_image_and_returns_embed(tmp_path):
  module = _load()
  first = tmp_path / "first.png"
  newest_but_wrong = tmp_path / "newest.png"
  first.write_bytes(b"\x89PNG exact requested bytes")
  newest_but_wrong.write_bytes(b"\x89PNG wrong bytes")

  receipt = module._publish(
    str(first), "chat-7", tmp_path / "data", "first result",
  )

  destination = Path(receipt["media_path"])
  assert destination.read_bytes() == first.read_bytes()
  assert destination.read_bytes() != newest_but_wrong.read_bytes()
  assert receipt["source_path"] == str(first.resolve())
  assert receipt["media_url"].startswith("/api/chats/chat-7/media/generated-")
  assert receipt["embed"] == (
    f"![first result]({receipt['media_url']})"
  )


@pytest.mark.parametrize(
  ("chat_id", "filename", "message"),
  [
    ("../other-chat", "image.png", "CHAT_ID"),
    ("chat-7", "notes.txt", "Image must use"),
  ],
)
def test_publish_rejects_unsafe_chat_or_non_image(
  tmp_path, chat_id, filename, message,
):
  module = _load()
  source = tmp_path / filename
  source.write_bytes(b"content")

  with pytest.raises(ValueError, match=message):
    module._publish(str(source), chat_id, tmp_path / "data", "image")
