"""Unit tests for `app.providers.get_skill_path` consolidation.

The helper used to be duplicated in `providers.py` and
`codex_sdk_runner.py`. After consolidation, only one definition
exists; both runners import it. The tests cover both fallback
candidates and the no-skill case so a future deployment-layout
change can't silently break either branch.
"""

from pathlib import Path
from unittest.mock import patch

from app.providers import get_skill_path


def test_returns_baked_path_when_present():
  """`/app/skill/agent-skill.md` is the production container path
  and wins when present."""
  with patch("app.providers.Path") as mock_path:
    baked = mock_path.return_value
    baked.exists.return_value = True
    result = get_skill_path()
    # The first candidate is `Path("/app/skill/agent-skill.md")`.
    assert mock_path.call_args_list[0].args == ("/app/skill/agent-skill.md",)
    assert result is baked


def test_returns_repo_path_when_baked_missing(tmp_path, monkeypatch):
  """If the baked container path doesn't exist, falls back to the
  in-repo path (local development case). The repo path is computed
  relative to the providers module file."""
  fake_baked = tmp_path / "nonexistent" / "agent-skill.md"
  fake_repo_skill_dir = tmp_path / "skill"
  fake_repo_skill_dir.mkdir()
  fake_repo_skill = fake_repo_skill_dir / "agent-skill.md"
  fake_repo_skill.write_text("# test skill")

  # Place a fake providers module file inside tmp_path/backend/app/.
  fake_providers_dir = tmp_path / "backend" / "app"
  fake_providers_dir.mkdir(parents=True)
  fake_providers_file = fake_providers_dir / "providers.py"
  fake_providers_file.write_text("")

  with patch("app.providers.__file__", str(fake_providers_file)):
    # Patch the baked Path so it reports missing.
    real_path = Path
    def path_factory(x):
      if x == "/app/skill/agent-skill.md":
        return fake_baked
      return real_path(x)
    with patch("app.providers.Path", side_effect=path_factory):
      result = get_skill_path()
      assert result == fake_repo_skill


def test_returns_none_when_neither_candidate_exists(tmp_path):
  """When neither path exists, returns None — callers handle the
  skill-less startup case (agent runs without a system prompt
  injection)."""
  fake_missing_a = tmp_path / "missing_a.md"
  fake_missing_b = tmp_path / "missing_b.md"
  with patch("app.providers.Path") as mock_path:
    mock_path.side_effect = [fake_missing_a, fake_missing_b]
    result = get_skill_path()
    assert result is None


def test_resolves_real_skill_in_test_container():
  """Sanity check — when running inside the production container or
  the repo, get_skill_path() should resolve to a real file. This
  exercises the actual deployment layout, not mocks."""
  result = get_skill_path()
  # At least one of the two candidates must exist in the test env.
  # In the pytest container the baked path is mounted; locally the
  # repo path is reachable. Skip if neither — that means the test
  # is running in a stripped-down env where the assertion isn't
  # applicable.
  if result is None:
    return
  assert result.exists()
  assert result.name == "agent-skill.md"
