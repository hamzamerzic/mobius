"""Initializes the agent experience file and writes upstream diffs."""

import os
import shutil
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
EXPERIENCE_PATH = DATA_DIR / "shared" / "agent-experience.md"
OLD_CONTEXT_PATH = DATA_DIR / "shared" / "agent-context.md"
SEED_PATH = Path("/app/scripts/seed-agent-experience.md")
DIFF_PATH = DATA_DIR / "shared" / "upstream-diff.txt"


def init():
  EXPERIENCE_PATH.parent.mkdir(parents=True, exist_ok=True)

  # Migrate from old agent-context.md if it exists and experience doesn't.
  # Keep the old file around in case it has useful content the agent wrote.
  if not EXPERIENCE_PATH.exists():
    if SEED_PATH.exists():
      shutil.copy2(SEED_PATH, EXPERIENCE_PATH)
      print(f"Seeded {EXPERIENCE_PATH} from {SEED_PATH}")
    else:
      EXPERIENCE_PATH.write_text(
        "# Agent experience\n\n(No seed file found — start fresh.)\n",
        encoding="utf-8",
      )
      print(f"Created empty {EXPERIENCE_PATH}")
  else:
    print(f"Already exists: {EXPERIENCE_PATH}")


if __name__ == "__main__":
  init()

  # Write upstream diff to a standalone file (overwritten each deploy).
  upstream_diff = os.environ.get("UPSTREAM_DIFF", "")
  if os.environ.get("UPSTREAM_CHANGED") == "true" and upstream_diff:
    DIFF_PATH.write_text(upstream_diff, encoding="utf-8")
    print(f"Wrote upstream diff to {DIFF_PATH}")
  else:
    # No changes — remove stale diff file if present.
    DIFF_PATH.unlink(missing_ok=True)
