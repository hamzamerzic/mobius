"""Pairing, revocation, and app-capability boundaries for Möbius Connect."""

import shlex
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app import models
from app.connect_runner import _run_command
from app.database import SessionLocal
from app.manifest_contract import ManifestContractError, validate_manifest_contract
from app.routes import connect as connect_routes
from app.schema_migrations import run_migrations, schema_migration_history


@pytest.fixture(autouse=True)
def _clear_connect_channels():
  connect_routes._channels.clear()
  yield
  connect_routes._channels.clear()


def _app_auth(client, auth, *, granted: bool) -> dict[str, str]:
  from test_app_fixtures import create_local_app

  app_id = create_local_app(
    client, auth, name="connect-test", description="test app",
  )["id"]
  session = SessionLocal()
  try:
    app = session.query(models.App).filter(models.App.id == app_id).first()
    app.connect_manage = granted
    session.commit()
  finally:
    session.close()
  minted = client.post(
    "/api/auth/app-token", json={"app_id": app_id}, headers=auth,
  )
  assert minted.status_code == 200, minted.text
  return {"Authorization": f"Bearer {minted.json()['token']}"}


def test_app_token_requires_connect_manage(client, auth):
  denied = _app_auth(client, auth, granted=False)
  response = client.get("/api/connect/hosts", headers=denied)
  assert response.status_code == 403
  assert "permissions.connect_manage=true" in response.json()["detail"]

  granted = _app_auth(client, auth, granted=True)
  assert client.get("/api/connect/hosts", headers=granted).json() == {"hosts": []}
  created = client.post(
    "/api/connect/hosts", headers=granted, json={"name": "Workstation"},
  )
  assert created.status_code == 200
  assert created.json()["name"] == "Workstation"


def test_pairing_is_one_time_and_delete_revokes_runner(client, auth):
  runner = client.get("/api/connect/runner")
  assert runner.status_code == 200
  assert runner.text.startswith("#!/usr/bin/env python3")

  created = client.post(
    "/api/connect/hosts", headers=auth, json={"name": "   "},
  )
  assert created.status_code == 200, created.text
  pairing = created.json()
  assert pairing["name"] == "My machine"
  assert pairing["pairing_code"] in pairing["install_command"]

  before = client.get("/api/connect/hosts", headers=auth).json()["hosts"]
  assert len(before) == 1
  public_host = before[0]
  assert public_host["id"] == pairing["id"]
  assert public_host["name"] == "My machine"
  assert public_host["paired"] is False
  assert public_host["online"] is False
  assert "pairing_code" not in public_host
  assert "token_sha256" not in public_host

  paired = client.post(
    "/api/connect/pair", json={"code": pairing["pairing_code"]},
  )
  assert paired.status_code == 200, paired.text
  runner_token = paired.json()["token"]
  assert client.post(
    "/api/connect/pair", json={"code": pairing["pairing_code"]},
  ).status_code == 400

  runner_auth = {"Authorization": f"Bearer {runner_token}"}
  assert client.post(
    "/api/connect/result", headers=runner_auth,
    json={"request_id": "not-pending"},
  ).status_code == 200

  removed = client.delete(f"/api/connect/hosts/{pairing['id']}", headers=auth)
  assert removed.status_code == 200
  assert client.post(
    "/api/connect/result", headers=runner_auth,
    json={"request_id": "not-pending"},
  ).status_code == 401


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group contract")
def test_runner_timeout_terminates_the_entire_command_tree(tmp_path: Path):
  """A timed-out command must not leave descendants running on the machine."""
  marker = tmp_path / "descendant-finished"
  descendant = (
    "import pathlib,time; time.sleep(0.5); "
    f"pathlib.Path({str(marker)!r}).touch()"
  )
  launcher = (
    "import subprocess,sys; "
    f"subprocess.Popen([sys.executable, '-c', {descendant!r}])"
  )
  # The launcher and its shell both exit immediately. The descendant retains
  # their captured pipes, reproducing the case where checking only the shell's
  # status would mistake a still-running command tree for completed work.
  cmd = f"{shlex.quote(sys.executable)} -c {shlex.quote(launcher)}"

  stdout, stderr, exit_code = _run_command(cmd, None, 0.05)

  assert stdout == ""
  assert "timed out" in stderr
  assert exit_code == 124
  time.sleep(0.6)
  assert not marker.exists()


def test_manifest_requires_boolean_connect_permission():
  manifest = {
    "id": "connect",
    "name": "Connect",
    "version": "0.1.0",
    "description": "Pair an external machine.",
    "entry": "index.jsx",
    "permissions": {"connect_manage": "yes"},
  }
  with pytest.raises(ManifestContractError, match="connect_manage"):
    validate_manifest_contract(manifest)


def test_connect_manage_reaches_a_ledgered_database(tmp_path: Path):
  eng = create_engine(f"sqlite:///{tmp_path / 'ledgered-apps.db'}")
  with eng.begin() as conn:
    conn.execute(text(
      "CREATE TABLE apps ("
      "id INTEGER PRIMARY KEY, name VARCHAR(255), slug VARCHAR(128), "
      "token_nonce VARCHAR(32), capability_contract JSON)"
    ))
    conn.execute(text(
      "CREATE TABLE schema_migrations ("
      "version VARCHAR(128) PRIMARY KEY, applied_at TIMESTAMP NOT NULL)"
    ))
    for version in (
      "0001_legacy_schema_convergence",
      "0002_chat_run_goal_objective",
      "0003_chat_run_root_identity",
      "0004_app_identity_required",
      "0005_connectors",
      "0006_connector_capability_identity",
      "0007_chat_has_messages",
      "0008_chat_search_documents",
      "0009_app_connections_manage",
      "0010_chat_pending_question_id",
      "0011_delegation_parent_wake",
      "0012_connector_oauth_gcloud",
      "0013_app_hosted_publication",
      "0014_chat_run_goal_plan",
      "0015_chat_run_goal_identity",
    ):
      conn.execute(text(
        "INSERT INTO schema_migrations (version, applied_at) "
        "VALUES (:version, '2026-08-22 00:00:00')"
      ), {"version": version})

  run_migrations(eng)
  columns = {column["name"] for column in inspect(eng).get_columns("apps")}
  assert "connect_manage" in columns
  assert "0016_app_connect_manage" in {
    entry["version"] for entry in schema_migration_history(eng)
  }
