"""Codex project-local skill materialization (parity with Claude skills="all")."""

from concurrent.futures import ThreadPoolExecutor
import threading
import time

import app.codex_skills as codex_skills

from app.codex_skills import (
  _MANIFEST,
  _safe_dir_name,
  sync_codex_skills,
  sync_codex_skills_for_prompt,
)


def _make_skill(root, name, description, body="Do the thing.", *, frontmatter=True):
  skills = root / "shared" / "skills"
  skills.mkdir(parents=True, exist_ok=True)
  text = (
    f"---\nname: {name}\ndescription: {description}\n---\n{body}\n"
    if frontmatter
    else f"# {name.title()}\n\n{body}\n"
  )
  (skills / f"{name}.md").write_text(
    text, encoding="utf-8",
  )


def test_sync_materializes_complete_flat_skill_and_prunes_removed(tmp_path):
  _make_skill(
    tmp_path, "alpha", "Alpha skill.", "Original body.", frontmatter=False,
  )
  _make_skill(tmp_path, "beta", "Beta skill.")

  names = sync_codex_skills(str(tmp_path), True)
  assert names == ["alpha", "beta"]
  source = tmp_path / "shared" / "skills" / "alpha.md"
  entry = tmp_path / ".codex" / "skills" / "alpha" / "SKILL.md"
  assert entry.is_file() and not entry.is_symlink()
  entry_text = entry.read_text(encoding="utf-8")
  assert "name: \"alpha\"" in entry_text
  assert "description: \"Original body.\"" in entry_text
  assert "# Alpha\n\nOriginal body." in entry_text
  assert "Read that file now" not in entry_text

  # The turn-start sync refreshes the complete entry when its source changes.
  source.write_text("# Alpha\n\nUpdated body.\n", encoding="utf-8")
  assert sync_codex_skills(str(tmp_path), True) == ["alpha", "beta"]
  assert "Updated body." in entry.read_text(encoding="utf-8")
  assert (tmp_path / ".codex" / "skills" / _MANIFEST).is_file()

  # A skill removed from the source is pruned on the next sync.
  (tmp_path / "shared" / "skills" / "beta.md").unlink()
  assert sync_codex_skills(str(tmp_path), True) == ["alpha"]
  assert not (tmp_path / ".codex" / "skills" / "beta").exists()


def test_sync_copies_directory_skill_with_its_resources(tmp_path):
  source = tmp_path / "shared" / "skills" / "toolkit"
  source.mkdir(parents=True)
  (source / "SKILL.md").write_text(
    "---\nname: toolkit\ndescription: Toolkit.\n---\nRead reference.md.\n",
    encoding="utf-8",
  )
  (source / "reference.md").write_text("Complete reference.\n", encoding="utf-8")

  assert sync_codex_skills(str(tmp_path), True) == ["toolkit"]
  entry = tmp_path / ".codex" / "skills" / "toolkit"
  assert entry.is_dir() and not entry.is_symlink()
  assert (entry / "SKILL.md").is_file()
  assert (entry / "reference.md").read_text(encoding="utf-8") == "Complete reference.\n"

  # Resource changes refresh the complete package rather than just SKILL.md.
  (source / "reference.md").write_text("Updated reference.\n", encoding="utf-8")
  assert sync_codex_skills(str(tmp_path), True) == ["toolkit"]
  assert (entry / "reference.md").read_text(encoding="utf-8") == "Updated reference.\n"


def test_directory_skill_symlinks_fall_back_instead_of_linking_to_source(tmp_path):
  source = tmp_path / "shared" / "skills" / "toolkit"
  source.mkdir(parents=True)
  (source / "SKILL.md").write_text(
    "---\nname: toolkit\ndescription: Toolkit.\n---\n",
    encoding="utf-8",
  )
  (source / "linked.md").symlink_to(source / "SKILL.md")

  assert sync_codex_skills_for_prompt(str(tmp_path), True) is False
  assert not (tmp_path / ".codex" / "skills" / "toolkit").exists()


def test_sync_upgrades_a_legacy_managed_pointer_to_a_complete_copy(tmp_path):
  _make_skill(tmp_path, "alpha", "Alpha skill.", "Complete instructions.")
  target = tmp_path / ".codex" / "skills"
  legacy = target / "alpha"
  legacy.mkdir(parents=True)
  (legacy / "SKILL.md").write_text("Read the other file.\n", encoding="utf-8")
  (target / _MANIFEST).write_text('{"names":["alpha"]}', encoding="utf-8")

  assert sync_codex_skills(str(tmp_path), True) == ["alpha"]
  entry = legacy / "SKILL.md"
  assert entry.is_file() and not entry.is_symlink()
  assert "Complete instructions." in entry.read_text(encoding="utf-8")


def test_entry_marker_recovers_pruning_after_a_lost_manifest(tmp_path):
  _make_skill(tmp_path, "alpha", "Alpha skill.")
  assert sync_codex_skills(str(tmp_path), True) == ["alpha"]
  target = tmp_path / ".codex" / "skills"
  (target / _MANIFEST).write_text("{broken", encoding="utf-8")
  (tmp_path / "shared" / "skills" / "alpha.md").unlink()

  assert sync_codex_skills(str(tmp_path), True) == []
  assert not (target / "alpha").exists()


def test_old_pointer_writer_cannot_overwrite_flat_source_and_cache_self_repairs(tmp_path):
  _make_skill(tmp_path, "alpha", "Alpha skill.", "Authoritative instructions.")
  source = tmp_path / "shared" / "skills" / "alpha.md"
  assert sync_codex_skills(str(tmp_path), True) == ["alpha"]
  cache = tmp_path / ".codex" / "skills" / "alpha" / "SKILL.md"

  # This is the exact dangerous operation used by the rolled-back writer.
  cache.write_text("Read the authoritative file now.\n", encoding="utf-8")
  assert "Authoritative instructions." in source.read_text(encoding="utf-8")

  assert sync_codex_skills(str(tmp_path), True) == ["alpha"]
  assert "Authoritative instructions." in cache.read_text(encoding="utf-8")


def test_old_pointer_writer_cannot_overwrite_directory_source_and_cache_self_repairs(tmp_path):
  source = tmp_path / "shared" / "skills" / "toolkit"
  source.mkdir(parents=True)
  authored = "---\nname: toolkit\ndescription: Toolkit.\n---\nReal instructions.\n"
  (source / "SKILL.md").write_text(authored, encoding="utf-8")
  (source / "reference.md").write_text("Reference.\n", encoding="utf-8")
  assert sync_codex_skills(str(tmp_path), True) == ["toolkit"]
  cache = tmp_path / ".codex" / "skills" / "toolkit" / "SKILL.md"

  cache.write_text("Read the authoritative file now.\n", encoding="utf-8")
  assert (source / "SKILL.md").read_text(encoding="utf-8") == authored

  assert sync_codex_skills(str(tmp_path), True) == ["toolkit"]
  assert cache.read_text(encoding="utf-8") == authored


def test_sync_disabled_prunes_only_managed_shims(tmp_path):
  _make_skill(tmp_path, "alpha", "Alpha skill.")
  sync_codex_skills(str(tmp_path), True)

  # A hand-placed, unmanaged skill must survive a disable/prune.
  hand = tmp_path / ".codex" / "skills" / "handmade"
  hand.mkdir(parents=True)
  (hand / "SKILL.md").write_text(
    "---\nname: handmade\ndescription: x\n---\n", encoding="utf-8"
  )

  assert sync_codex_skills(str(tmp_path), False) == []
  assert not (tmp_path / ".codex" / "skills" / "alpha").exists()
  assert (hand / "SKILL.md").is_file()


def test_sync_does_not_replace_same_named_unmanaged_skill(tmp_path):
  _make_skill(tmp_path, "alpha", "Alpha skill.")
  hand = tmp_path / ".codex" / "skills" / "alpha"
  hand.mkdir(parents=True)
  authored = hand / "SKILL.md"
  authored.write_text("hand-authored\n", encoding="utf-8")

  assert sync_codex_skills(str(tmp_path), True) == []
  assert authored.read_text(encoding="utf-8") == "hand-authored\n"


def test_concurrent_chat_starts_serialize_one_complete_cache_publish(
  tmp_path, monkeypatch,
):
  _make_skill(tmp_path, "alpha", "Alpha skill.")
  original = codex_skills._materialize_entry
  active = 0
  max_active = 0
  state_lock = threading.Lock()

  def slow_materialize(*args, **kwargs):
    nonlocal active, max_active
    with state_lock:
      active += 1
      max_active = max(max_active, active)
    try:
      time.sleep(0.03)
      return original(*args, **kwargs)
    finally:
      with state_lock:
        active -= 1

  monkeypatch.setattr(codex_skills, "_materialize_entry", slow_materialize)
  with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(
      lambda _: sync_codex_skills(str(tmp_path), True), range(2),
    ))

  assert results == [["alpha"], ["alpha"]]
  assert max_active == 1
  assert sync_codex_skills_for_prompt(str(tmp_path), True) is True


def test_safe_dir_name_sanitizes():
  assert _safe_dir_name("building-apps") == "building-apps"
  assert _safe_dir_name("a/b c") == "a-b-c"
  assert _safe_dir_name("..") is None
  assert _safe_dir_name("") is None
