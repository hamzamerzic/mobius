#!/usr/bin/env python3
"""Publish one exact local raster image into the current chat's media."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid


_CHAT_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
_MAX_BYTES = 25 * 1024 * 1024


def _args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description=(
      "Copy the exact generated image named by SOURCE into this chat and "
      "print its durable path, URL, and ready-to-paste embed."
    ),
  )
  parser.add_argument("source")
  parser.add_argument("--alt", default="generated image")
  return parser.parse_args()


def _publish(source_arg: str, chat_id: str, data_dir: Path, alt: str) -> dict:
  if not _CHAT_ID_RE.fullmatch(chat_id):
    raise ValueError("CHAT_ID must be 1-64 letters, digits, or hyphens.")
  try:
    source = Path(source_arg).resolve(strict=True)
  except (OSError, RuntimeError) as exc:
    raise ValueError(f"Cannot resolve image source: {exc}") from exc
  if not source.is_file():
    raise ValueError("Image source is not a file.")
  suffix = source.suffix.lower()
  if suffix not in _IMAGE_SUFFIXES:
    allowed = ", ".join(sorted(_IMAGE_SUFFIXES))
    raise ValueError(f"Image must use one of: {allowed}.")
  size = source.stat().st_size
  if size <= 0:
    raise ValueError("Image source is empty.")
  if size > _MAX_BYTES:
    raise ValueError(f"Image exceeds the {_MAX_BYTES}-byte publishing limit.")

  media_dir = data_dir / "chats" / chat_id / "media"
  media_dir.mkdir(parents=True, exist_ok=True)
  filename = f"generated-{uuid.uuid4().hex[:16]}{suffix}"
  destination = media_dir / filename
  temporary = None
  try:
    with tempfile.NamedTemporaryFile(
      prefix=".publish-", suffix=suffix, dir=media_dir, delete=False,
    ) as staged:
      temporary = Path(staged.name)
      with source.open("rb") as incoming:
        shutil.copyfileobj(incoming, staged)
      staged.flush()
      os.fsync(staged.fileno())
    temporary.chmod(0o644)
    os.replace(temporary, destination)
  finally:
    if temporary is not None:
      temporary.unlink(missing_ok=True)

  media_url = f"/api/chats/{chat_id}/media/{filename}"
  safe_alt = alt.replace("\\", "\\\\").replace("]", "\\]")
  return {
    "source_path": str(source),
    "media_path": str(destination),
    "media_url": media_url,
    "embed": f"![{safe_alt}]({media_url})",
  }


def main() -> None:
  args = _args()
  chat_id = os.environ.get("CHAT_ID", "")
  data_dir = Path(os.environ.get("DATA_DIR", "/data"))
  try:
    receipt = _publish(args.source, chat_id, data_dir, args.alt)
  except (OSError, ValueError) as exc:
    raise SystemExit(f"publish_chat_image.py: {exc}") from exc
  print(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
  main()
