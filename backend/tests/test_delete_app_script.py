"""Deletion helper preserves the exact recovery handle."""

import importlib.util
import json
from pathlib import Path
import sys


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "delete_app.py"


def _load():
  spec = importlib.util.spec_from_file_location("delete_app_script", SCRIPT)
  module = importlib.util.module_from_spec(spec)
  assert spec.loader is not None
  spec.loader.exec_module(module)
  return module


class _Response:
  def __init__(self, payload=b""):
    self.payload = payload

  def __enter__(self):
    return self

  def __exit__(self, *_args):
    return False

  def read(self):
    return self.payload


def test_delete_fetches_exact_id_then_returns_recovery_receipt(
  monkeypatch, capsys,
):
  module = _load()
  monkeypatch.setattr(
    sys, "argv", ["delete_app.py", "17", "--confirm"],
  )
  monkeypatch.setenv("AGENT_TOKEN", "agent-token")
  monkeypatch.setenv("API_BASE_URL", "http://mobius.test/")
  requests = []

  def respond(request, timeout):
    requests.append((request.full_url, request.get_method()))
    if request.get_method() == "GET":
      return _Response(json.dumps({
        "id": 17,
        "name": "Duplicate name",
        "slug": "duplicate-name-2",
        "source_dir": "/data/apps/duplicate-name-2",
      }).encode())
    return _Response()

  monkeypatch.setattr(module.urllib.request, "urlopen", respond)

  module.main()

  assert requests == [
    ("http://mobius.test/api/apps/17", "GET"),
    ("http://mobius.test/api/apps/17", "DELETE"),
  ]
  assert json.loads(capsys.readouterr().out) == {
    "status": "deleted",
    "app_id": 17,
    "name": "Duplicate name",
    "slug": "duplicate-name-2",
    "source_dir": "/data/apps/duplicate-name-2",
    "recover_path": "/api/apps/17/recover",
    "recoverable_for_days": 7,
  }


def test_delete_refuses_mismatched_lookup_identity(monkeypatch, capsys):
  module = _load()
  monkeypatch.setattr(
    sys, "argv", ["delete_app.py", "17", "--confirm"],
  )
  monkeypatch.setenv("AGENT_TOKEN", "agent-token")
  monkeypatch.setattr(
    module.urllib.request,
    "urlopen",
    lambda request, timeout: _Response(json.dumps({"id": 18}).encode()),
  )

  try:
    module.main()
  except SystemExit as exc:
    assert exc.code == 1
  else:
    raise AssertionError("mismatched app identity should fail")

  assert "requested numeric id" in capsys.readouterr().err
