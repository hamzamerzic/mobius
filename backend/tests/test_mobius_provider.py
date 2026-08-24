from __future__ import annotations

import json

from app import providers
from app.schemas import AgentSettingsOverride, ChatProviderSwitch


def test_trial_provider_requires_linked_broker(monkeypatch, tmp_path):
  provider = providers.MobiusProvider()
  monkeypatch.setattr(provider, "_identity", lambda: {"linked": False})
  assert "Möbius · You" in provider.check_auth(str(tmp_path))
  monkeypatch.setattr(provider, "_identity", lambda: {"linked": True})
  assert provider.check_auth(str(tmp_path)) is None


def test_trial_provider_config_uses_only_local_broker_marker(tmp_path):
  provider = providers.MobiusProvider()
  env = provider.build_env(
    {
      "OPENAI_API_KEY": "must-not-leak",
      "PRIVATE_PROVIDER_API_KEY": "must-not-leak",
    },
    str(tmp_path),
    "chat-1",
  )
  config = (tmp_path / "cli-auth" / "mobius" / "config.toml").read_text()

  assert env["OPENAI_API_KEY"] == ""
  assert env["PRIVATE_PROVIDER_API_KEY"] == ""
  assert env["MOBIUS_LOCAL_BROKER_KEY"] == "local-broker"
  assert env["CODEX_HOME"] == str(tmp_path / "cli-auth" / "mobius")
  assert "http://127.0.0.1:8765/v1" in config
  assert "MOBIUS_LOCAL_BROKER_KEY" in config
  assert "PRIVATE_PROVIDER" not in config
  assert "secret" not in config.lower()


def test_subscription_catalog_exposes_one_product_model():
  payload = json.loads(providers.MobiusProvider._catalog_path().read_text())
  assert [row["slug"] for row in payload["models"]] == ["inkling"]
  assert [row["display_name"] for row in payload["models"]] == ["Evolve"]
  assert providers.MODEL_LABELS["inkling"] == "Evolve"
  assert providers.DEFAULT_MODELS["mobius"] == "inkling"
  assert providers.provider_runtime_kind("mobius") == "codex_sdk"
  fallback = providers._fallback_models("mobius")
  assert [row["id"] for row in fallback] == ["inkling"]
  assert [row["label"] for row in fallback] == ["Evolve"]


def test_evolve_is_valid_for_atomic_provider_handoff():
  switch = ChatProviderSwitch(
    provider="mobius",
    agent_settings_json=AgentSettingsOverride(model="inkling", effort="high"),
    switch_id="switch-to-evolve",
  )
  assert switch.provider == "mobius"


def test_subscription_never_becomes_an_implicit_connected_default(monkeypatch):
  monkeypatch.setattr(
    providers.MobiusProvider, "check_auth", lambda self, _data_dir: None,
  )
  monkeypatch.setattr(
    providers.CodexProvider, "check_auth", lambda self, _data_dir: "missing",
  )
  monkeypatch.setattr(
    providers.ClaudeProvider, "check_auth", lambda self, _data_dir: "missing",
  )

  assert providers.authenticated_provider_ids("/data") == []
  assert providers.resolve_default_provider("/data", "claude") == "claude"
