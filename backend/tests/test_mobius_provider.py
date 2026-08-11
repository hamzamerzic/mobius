from __future__ import annotations

import json

from app import providers


def test_trial_provider_requires_linked_broker(monkeypatch, tmp_path):
  provider = providers.MobiusProvider()
  monkeypatch.setattr(provider, "_identity", lambda: {"linked": False})
  assert "$2 trial" in provider.check_auth(str(tmp_path))
  monkeypatch.setattr(provider, "_identity", lambda: {"linked": True})
  assert provider.check_auth(str(tmp_path)) is None


def test_trial_provider_config_uses_only_local_broker_marker(tmp_path):
  provider = providers.MobiusProvider()
  env = provider.build_env(
    {
      "OPENAI_API_KEY": "must-not-leak",
      "FIREWORKS_API_KEY": "must-not-leak",
    },
    str(tmp_path),
    "chat-1",
  )
  config = (tmp_path / "cli-auth" / "mobius" / "config.toml").read_text()

  assert env["OPENAI_API_KEY"] == ""
  assert env["FIREWORKS_API_KEY"] == ""
  assert env["MOBIUS_LOCAL_BROKER_KEY"] == "local-broker"
  assert env["CODEX_HOME"] == str(tmp_path / "cli-auth" / "mobius")
  assert "http://127.0.0.1:8765/v1" in config
  assert "MOBIUS_LOCAL_BROKER_KEY" in config
  assert "fireworks" not in config.lower()
  assert "secret" not in config.lower()


def test_trial_catalog_exposes_distinct_fireworks_models():
  payload = json.loads(providers.MobiusProvider._catalog_path().read_text())
  assert [row["slug"] for row in payload["models"]] == [
    "inkling", "deepseek-flash", "glm",
  ]
  assert providers.DEFAULT_MODELS["mobius"] == "inkling"
  assert providers.provider_runtime_kind("mobius") == "codex_sdk"
  assert [row["id"] for row in providers._fallback_models("mobius")] == [
    "inkling", "deepseek-flash", "glm",
  ]
