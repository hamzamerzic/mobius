from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _compose():
  return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


def test_external_recovery_worker_is_unprivileged_and_has_no_host_control():
  worker = _compose()["services"]["recovery"]
  assert worker["profiles"] == ["recovery"]
  assert worker["read_only"] is True
  assert worker["cap_drop"] == ["ALL"]
  assert "no-new-privileges:true" in worker["security_opt"]
  assert worker.get("volumes", []) == []
  assert all("docker.sock" not in item for item in worker.get("volumes", []))
  assert worker["ports"] == [
    "127.0.0.1:${MOBIUS_RECOVERY_PORT:-18003}:8000"
  ]


def test_only_root_target_mounts_the_stopped_app_data():
  services = _compose()["services"]
  target = services["recovery-target"]
  worker = services["recovery"]
  assert target["profiles"] == ["recovery"]
  assert target["volumes"] == ["app_data:/data"]
  assert any(
    item == "MOBIUS_BOOT_MODE=recovery" for item in target["environment"]
  )
  assert worker.get("volumes") is None
  assert worker["depends_on"]["recovery-target"]["condition"] == "service_healthy"


def test_lifecycle_pulls_latest_before_stopping_app_and_restores_on_finish():
  script = (ROOT / "scripts" / "mobiusctl").read_text()
  start = script.index("compose pull recovery")
  stop = script.index("compose stop app", start)
  launch = script.index("compose up -d --force-recreate recovery-target recovery")
  assert start < stop < launch

  finish = script.index("finish_recovery()")
  down = script.index("recovery_down", finish)
  app_up = script.index("docker compose up -d app", finish)
  health = script.index("Waiting for Mobius health", finish)
  assert down < app_up < health


def test_app_sudo_is_explicit_and_defaults_off():
  app_env = _compose()["services"]["app"]["environment"]
  assert "MOBIUS_AGENT_SUDO=${MOBIUS_AGENT_SUDO:-0}" in app_env
