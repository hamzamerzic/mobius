import os
import subprocess
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
  assert "/state:uid=10001,gid=10001,mode=0700" in worker["tmpfs"]
  assert "HOME=/state" in worker["environment"]
  assert "MOBIUS_RECOVERY_SECURE_COOKIE=0" in worker["environment"]


def test_only_root_target_mounts_the_stopped_app_data():
  services = _compose()["services"]
  target = services["recovery-target"]
  worker = services["recovery"]
  assert target["profiles"] == ["recovery"]
  assert target.get("init") is None
  assert target["read_only"] is True
  assert set(target["cap_drop"]) == {"NET_ADMIN", "NET_RAW"}
  assert target["tmpfs"] == ["/tmp", "/run"]
  assert target["volumes"] == ["app_data:/data"]
  assert any(
    item == "MOBIUS_BOOT_MODE=recovery" for item in target["environment"]
  )
  assert target["healthcheck"] == {"disable": True}
  assert worker.get("volumes") is None
  assert worker["depends_on"]["recovery-target"]["condition"] == "service_started"


def test_lifecycle_pulls_latest_before_stopping_app_and_restores_on_finish():
  script = (ROOT / "scripts" / "mobiusctl").read_text()
  assert "/?token=" not in script
  assert "Paste this one-time code into the Recovery sign-in form" in script
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


def _mobiusctl(tmp_path, action, *, state=None, extra_env=None):
  state_path = state or tmp_path / "recovery.env"
  env = os.environ.copy()
  env["MOBIUS_RECOVERY_STATE_FILE"] = str(state_path)
  env.update(extra_env or {})
  result = subprocess.run(
    [str(ROOT / "scripts" / "mobiusctl"), "recovery", action],
    cwd=ROOT,
    env=env,
    text=True,
    capture_output=True,
    timeout=10,
  )
  return result, state_path


def test_lifecycle_rejects_user_image_shell_injection_before_writing_state(
  tmp_path,
):
  marker = tmp_path / "injected"
  malicious = f"ghcr.io/mobius/recovery:stable\n$(touch {marker})"
  result, state = _mobiusctl(
    tmp_path,
    "start",
    extra_env={"MOBIUS_RECOVERY_IMAGE": malicious},
  )
  assert result.returncode != 0
  assert "unsafe characters" in result.stderr
  assert not marker.exists()
  assert not state.exists()


def test_lifecycle_never_sources_injected_state(tmp_path):
  marker = tmp_path / "injected"
  state = tmp_path / "recovery.env"
  state.write_text(
    "MOBIUS_RECOVERY_TARGET_TOKEN=" + "t" * 43 + "\n"
    "MOBIUS_RECOVERY_LOCAL_TOKEN=" + "l" * 43 + "\n"
    "MOBIUS_RECOVERY_PORT=18003\n"
    "MOBIUS_RECOVERY_IMAGE=ghcr.io/mobius/recovery:stable\n"
    f"$(touch {marker})\n"
  )
  state.chmod(0o600)
  result, _ = _mobiusctl(tmp_path, "status", state=state)
  assert result.returncode != 0
  assert "unexpected or malformed line" in result.stderr
  assert not marker.exists()


def test_lifecycle_rejects_unsafe_state_files(tmp_path):
  content = (
    "MOBIUS_RECOVERY_TARGET_TOKEN=" + "t" * 43 + "\n"
    "MOBIUS_RECOVERY_LOCAL_TOKEN=" + "l" * 43 + "\n"
    "MOBIUS_RECOVERY_PORT=18003\n"
    "MOBIUS_RECOVERY_IMAGE=ghcr.io/mobius/recovery:stable\n"
  )

  permissive = tmp_path / "permissive.env"
  permissive.write_text(content)
  permissive.chmod(0o644)
  result, _ = _mobiusctl(tmp_path, "status", state=permissive)
  assert result.returncode != 0
  assert "permissions must be" in result.stderr

  original = tmp_path / "original.env"
  original.write_text(content)
  original.chmod(0o600)
  hardlink = tmp_path / "hardlink.env"
  os.link(original, hardlink)
  result, _ = _mobiusctl(tmp_path, "status", state=hardlink)
  assert result.returncode != 0
  assert "exactly one hard link" in result.stderr

  symlink = tmp_path / "symlink.env"
  symlink.symlink_to(original)
  result, _ = _mobiusctl(tmp_path, "status", state=symlink)
  assert result.returncode != 0
  assert "must not be a symlink" in result.stderr
