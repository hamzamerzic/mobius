from pathlib import Path


ENTRYPOINT = Path(__file__).resolve().parents[1] / "scripts" / "entrypoint.sh"


def test_normal_boot_removes_retired_authority_before_platform_import():
  source = ENTRYPOINT.read_text(encoding="utf-8")
  start = source.index("# Retire embedded-recovery authority")
  end = source.index("# Per-boot fail-closed proof", start)
  block = source[start:end]

  assert source.index("case \"${MOBIUS_BOOT_MODE:-normal}\"") < start
  assert start < source.index("# PHASE 1: Platform layer")
  assert 'rm -f -- "$_retired_recovery_state"' in block
  assert "exit 70" in block
  for retired in (
    "/data/.recovery-secret",
    "/data/.recovery-owner.json",
    "/data/.recover-pending",
  ):
    assert retired in block


def test_legacy_recovery_transcript_is_explicitly_preserved():
  source = ENTRYPOINT.read_text(encoding="utf-8")
  start = source.index("# Retire embedded-recovery authority")
  end = source.index("# Per-boot fail-closed proof", start)
  block = source[start:end]

  assert "recovery_chat.jsonl" in block
  assert "/data/recovery_chat.jsonl" not in block
