from __future__ import annotations

import base64
import errno
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


_TARGET_PATH = (
  Path(__file__).resolve().parents[1] / "recovery_target" / "targetd.py"
)
_BOOT_ID = "B" * 32


def _base64url(value: bytes) -> str:
  return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _capability_token(
  private_key: Ed25519PrivateKey,
  *,
  now: int | None = None,
  scope: str = "session",
  **overrides,
) -> tuple[str, dict]:
  issued_at = int(time.time()) if now is None else now
  claims = {
    "v": 1,
    "iss": "mobius.you",
    "aud": "mobius-recovery-target",
    "sub": "instance-123",
    "dep": "deployment-789",
    "scp": scope,
    "iat": issued_at,
    "nbf": issued_at,
    "exp": issued_at + (30 if scope == "probe" else 300),
  }
  if scope == "session":
    claims.update({"sid": "session-456", "bid": _BOOT_ID})
  claims.update(overrides)
  payload = json.dumps(
    claims, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
  ).encode("utf-8")
  payload_segment = _base64url(payload)
  signed = f"mrc1.{payload_segment}".encode("ascii")
  token = f"mrc1.{payload_segment}.{_base64url(private_key.sign(signed))}"
  return token, claims


def _configure_live_capabilities(target):
  private_key = Ed25519PrivateKey.generate()
  target._AUTH_MODE = "capability"
  target._CAPABILITY_PUBLIC_KEY = private_key.public_key()
  target._LOCAL_INSTANCE_ID = "instance-123"
  target._LOCAL_DEPLOYMENT_ID = "deployment-789"
  target._LOCAL_BOOT_ID = _BOOT_ID
  target._TARGET_EXPIRES_AT = None
  return private_key


def _configure_live_attach_gate(target, path: Path, *, ready: bool) -> None:
  path.write_text(f"ready:{_BOOT_ID}\n" if ready else "", encoding="ascii")
  path.chmod(0o600)
  target._ATTACH_READY_FILE = path
  target._ATTACH_READY.clear()


def _revoked_response(session_id: str) -> dict:
  return {
    "status": "revoked",
    "deployment_id": "deployment-789",
    "session_id": session_id,
  }


@pytest.fixture()
def target(monkeypatch):
  spec = importlib.util.spec_from_file_location("test_recovery_targetd", _TARGET_PATH)
  assert spec and spec.loader
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  module._STARTUP_TOKEN_DIGEST = module._token_digest(b"t" * 43)
  module._TARGET_EXPIRES_AT = int(time.time()) + 3600
  return module


@contextmanager
def _server(target):
  server = target._DualStackServer(("::", 0), target._Handler)
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  try:
    yield f"http://127.0.0.1:{server.server_port}"
  finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def _request(url, path, *, token="t" * 43, body=None, timeout=15):
  headers = {"Authorization": f"Bearer {token}"}
  data = None
  method = "GET"
  if body is not None:
    headers["Content-Type"] = "application/json"
    data = json.dumps(body).encode()
    method = "POST"
  request = urllib.request.Request(
    url + path, data=data, headers=headers, method=method
  )
  with urllib.request.urlopen(request, timeout=timeout) as response:
    return response.status, json.load(response)


def _socket_response(sock) -> bytes:
  chunks = []
  while True:
    chunk = sock.recv(4096)
    if not chunk:
      return b"".join(chunks)
    chunks.append(chunk)


def test_dual_stack_health_is_authenticated(target):
  with _server(target) as url:
    with pytest.raises(urllib.error.HTTPError) as denied:
      _request(url, "/v1/health", token="wrong")
    assert denied.value.code == 401

    status, body = _request(url, "/v1/health")
    assert status == 200
    assert body == {
      "protocol": "mobius-recovery-target/v1",
      "target": "mobius",
      "mode": "recovery",
      "build_sha": "unknown",
      "expires_at": target._TARGET_EXPIRES_AT,
    }

    with pytest.raises(urllib.error.HTTPError) as legacy_revoke:
      _request(url, "/v1/revoke", body={})
    assert legacy_revoke.value.code == 404


def test_live_health_uses_signed_capability_and_reports_bound_deployment(
  target, tmp_path,
):
  private_key = _configure_live_capabilities(target)
  _configure_live_attach_gate(target, tmp_path / "attach-ready", ready=True)
  token, claims = _capability_token(private_key, scope="probe")
  assert len(token) <= target.MAX_CAPABILITY_TOKEN_BYTES

  with _server(target) as url:
    with pytest.raises(urllib.error.HTTPError) as denied:
      _request(url, "/v1/health", token="t" * 43)
    assert denied.value.code == 401

    status, body = _request(url, "/v1/health", token=token)
  assert status == 200
  assert body == {
    "protocol": "mobius-recovery-target/v1",
    "target": "mobius",
    "mode": "normal",
    "attachment": "live",
    "build_sha": "unknown",
    "expires_at": claims["exp"],
    "deployment_id": "deployment-789",
    "boot_id": _BOOT_ID,
  }


def test_live_session_scope_serves_health_exec_and_filesystem(
  target, tmp_path,
):
  private_key = _configure_live_capabilities(target)
  _configure_live_attach_gate(target, tmp_path / "attach-ready", ready=True)
  token, _claims = _capability_token(private_key)
  payload = tmp_path / "payload.txt"
  payload.write_text("repair-data", encoding="ascii")

  with _server(target) as url:
    assert _request(url, "/v1/health", token=token)[1]["boot_id"] == _BOOT_ID
    status, result = _request(
      url,
      "/v1/exec",
      token=token,
      body={"argv": ["/bin/true"], "cwd": str(tmp_path)},
    )
    assert status == 200 and result["exit_code"] == 0
    status, result = _request(
      url, "/v1/fs/read", token=token, body={"path": str(payload)},
    )
    assert status == 200
    assert base64.b64decode(result["data_base64"]) == b"repair-data"


@pytest.mark.parametrize(
  ("path", "body"),
  (
    ("/v1/exec", {"argv": ["/bin/true"]}),
    ("/v1/fs/read", {"path": "/tmp/anything"}),
    ("/v1/fs/write", {"path": "/tmp/anything", "data_base64": ""}),
    ("/v1/fs/list", {"path": "/tmp"}),
    ("/v1/revoke", {}),
  ),
)
def test_probe_scope_cannot_exec_access_files_or_revoke(
  target, tmp_path, path, body,
):
  private_key = _configure_live_capabilities(target)
  _configure_live_attach_gate(target, tmp_path / "attach-ready", ready=True)
  token, _claims = _capability_token(private_key, scope="probe")
  with _server(target) as url:
    with pytest.raises(urllib.error.HTTPError) as denied:
      _request(url, path, token=token, body=body)
  assert denied.value.code == 403
  assert json.load(denied.value)["error"]["code"] == "insufficient_scope"


def test_session_capability_is_bound_to_this_exact_container_boot(target):
  private_key = _configure_live_capabilities(target)
  token, claims = _capability_token(private_key)
  assert len(token) <= target.MAX_CAPABILITY_TOKEN_BYTES
  assert target._verify_capability_token(token) == claims

  wrong_token, _claims = _capability_token(private_key, bid="W" * 32)
  with pytest.raises(target.RequestError) as wrong_boot:
    target._verify_capability_token(wrong_token)
  assert wrong_boot.value.code == "unauthorized"

  # A container restart creates a new boot identity even when Railway retains
  # the same deployment id. The previously valid root session fails closed.
  target._LOCAL_BOOT_ID = "N" * 32
  with pytest.raises(target.RequestError) as old_boot:
    target._verify_capability_token(token)
  assert old_boot.value.code == "unauthorized"


def test_probe_has_no_session_or_boot_authority_claims(target):
  private_key = _configure_live_capabilities(target)
  token, claims = _capability_token(private_key, scope="probe")
  assert "sid" not in claims
  assert "bid" not in claims
  assert target._verify_capability_token(token) == claims

  token, _claims = _capability_token(
    private_key, scope="probe", sid="forbidden-session",
  )
  with pytest.raises(target.RequestError) as extra_claim:
    target._verify_capability_token(token)
  assert extra_claim.value.code == "unauthorized"


def test_live_target_denies_startup_window_until_entrypoint_init_completes(
  target, tmp_path,
):
  private_key = _configure_live_capabilities(target)
  ready_file = tmp_path / "attach-ready"
  _configure_live_attach_gate(target, ready_file, ready=False)
  token, _claims = _capability_token(private_key, scope="probe")

  with _server(target) as url:
    with pytest.raises(urllib.error.HTTPError) as starting:
      _request(url, "/v1/health", token=token)
    assert starting.value.code == 503
    assert json.load(starting.value)["error"]["code"] == "attach_not_ready"

    # A stale or foreign boot marker cannot release the gate.
    ready_file.write_text(f"ready:{'S' * 32}\n", encoding="ascii")
    with pytest.raises(urllib.error.HTTPError) as stale:
      _request(url, "/v1/health", token=token)
    assert stale.value.code == 503

    # No application health result participates in this gate. The private
    # marker means only that entrypoint initialization reached its final handoff.
    ready_file.write_text(f"ready:{_BOOT_ID}\n", encoding="ascii")
    status, health = _request(url, "/v1/health", token=token)
  assert status == 200
  assert health["attachment"] == "live"
  assert not ready_file.exists()


def test_live_target_accepts_ready_marker_written_before_target_initializes(
  target, monkeypatch,
):
  fd, ready_name = tempfile.mkstemp(
    prefix="mobius-recovery-attach-ready.", dir="/tmp",
  )
  ready_file = Path(ready_name)
  try:
    with os.fdopen(fd, "wb") as handle:
      handle.write(f"ready:{_BOOT_ID}\n".encode("ascii"))
    monkeypatch.setenv(target.ATTACH_READY_FILE_ENV, ready_name)

    assert target._read_attach_ready_file() == ready_file
    target._AUTH_MODE = "capability"
    target._LOCAL_BOOT_ID = _BOOT_ID
    target._ATTACH_READY_FILE = ready_file
    target._ATTACH_READY.clear()
    assert target._attach_is_ready()
    assert not ready_file.exists()
  finally:
    ready_file.unlink(missing_ok=True)


@pytest.mark.parametrize("kind", ("symlink", "hardlink", "public_mode"))
def test_live_attach_marker_rejects_insecure_files(target, monkeypatch, kind):
  fd, source_name = tempfile.mkstemp(
    prefix="mobius-recovery-attach-ready.", dir="/tmp",
  )
  os.close(fd)
  source = Path(source_name)
  candidate = source
  extra: Path | None = None
  try:
    if kind == "symlink":
      extra = Path(source_name + ".symlink")
      extra.symlink_to(source)
      candidate = extra
    elif kind == "hardlink":
      extra = Path(source_name + ".hardlink")
      os.link(source, extra)
      candidate = extra
    else:
      source.chmod(0o644)
    monkeypatch.setenv(target.ATTACH_READY_FILE_ENV, str(candidate))
    with pytest.raises(RuntimeError, match="insecure"):
      target._read_attach_ready_file()
  finally:
    if extra is not None:
      extra.unlink(missing_ok=True)
    source.unlink(missing_ok=True)


def test_live_session_self_revoke_is_pre_ready_idempotent_and_scoped(
  target, tmp_path,
):
  private_key = _configure_live_capabilities(target)
  _configure_live_attach_gate(target, tmp_path / "attach-ready", ready=False)
  revoked_token, _revoked_claims = _capability_token(
    private_key, sid="session-revoked",
  )
  other_token, _other_claims = _capability_token(
    private_key, sid="session-other",
  )

  with _server(target) as url:
    status, result = _request(
      url, "/v1/revoke", token=revoked_token, body={},
    )
    assert status == 200
    assert result == _revoked_response("session-revoked")

    # The same still-valid signed token may retry its own revoke.
    status, result = _request(
      url, "/v1/revoke", token=revoked_token, body={},
    )
    assert status == 200
    assert result == _revoked_response("session-revoked")

    with pytest.raises(urllib.error.HTTPError) as revoked:
      _request(url, "/v1/health", token=revoked_token)
    assert revoked.value.code == 401
    assert json.load(revoked.value)["error"]["code"] == "auth_revoked"

    # Revoke never accepts a caller-selected session id and does not affect a
    # different signed session.
    with pytest.raises(urllib.error.HTTPError) as selected:
      _request(
        url, "/v1/revoke", token=other_token,
        body={"sid": "session-revoked"},
      )
    assert selected.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as still_starting:
      _request(url, "/v1/health", token=other_token)
    assert still_starting.value.code == 503
    assert json.load(still_starting.value)["error"]["code"] == "attach_not_ready"


def test_session_revoke_kills_only_that_sessions_active_exec(target, tmp_path):
  _configure_live_capabilities(target)
  expires_at = int(time.time()) + 30
  first_ready = tmp_path / "first.ready"
  second_ready = tmp_path / "second.ready"

  def command(marker: Path, delay: float, session_id: str):
    return target._run_exec({
      "argv": [
        sys.executable, "-c",
        f"import pathlib,time; pathlib.Path({str(marker)!r}).touch(); "
        f"time.sleep({delay}); print({session_id!r})",
      ],
      "cwd": str(tmp_path),
      "timeout_seconds": 10,
    }, capability_expires_at=expires_at, capability_session_id=session_id)

  with ThreadPoolExecutor(max_workers=2) as executor:
    first = executor.submit(command, first_ready, 30, "session-first")
    second = executor.submit(command, second_ready, 0.8, "session-second")
    deadline = time.monotonic() + 3
    while (
      (not first_ready.exists() or not second_ready.exists())
      and time.monotonic() < deadline
    ):
      time.sleep(0.01)
    assert first_ready.exists() and second_ready.exists()
    assert target._revoke_capability_session({
      "sid": "session-first", "dep": "deployment-789", "bid": _BOOT_ID,
      "exp": expires_at,
    }) == _revoked_response("session-first")

  with pytest.raises(target.RequestError) as revoked:
    first.result()
  assert revoked.value.code == "auth_revoked"
  survivor = second.result()
  assert survivor["exit_code"] == 0
  assert base64.b64decode(survivor["stdout_base64"]) == b"session-second\n"


def test_session_revoke_ignores_a_reused_supervisor_pid(target, monkeypatch):
  target._ACTIVE_SUPERVISORS[4242] = ("session-stale", 100)
  signals = []
  tree_walks = []
  monkeypatch.setattr(target, "_process_record", lambda _pid: (1, 101))
  monkeypatch.setattr(
    target, "_signal_recorded_process",
    lambda *args: signals.append(args),
  )
  monkeypatch.setattr(
    target, "_stop_and_kill_descendants",
    lambda pid: tree_walks.append(pid),
  )

  target._retire_session_supervisors("session-stale")

  assert signals == []
  assert tree_walks == []


def test_revoked_session_denylist_is_bounded_and_pruned(target, monkeypatch):
  monkeypatch.setattr(target, "MAX_REVOKED_SESSIONS", 1)
  now = 1_800_000_000
  monkeypatch.setattr(target.time, "time", lambda: now)
  assert target._revoke_capability_session({
    "sid": "session-one", "dep": "deployment-789", "bid": _BOOT_ID,
    "exp": now + 10,
  }) == _revoked_response("session-one")
  with pytest.raises(target.RequestError) as full:
    target._revoke_capability_session({
      "sid": "session-two", "dep": "deployment-789", "bid": _BOOT_ID,
      "exp": now + 20,
    })
  assert full.value.code == "revocation_capacity"
  assert full.value.status == target.HTTPStatus.SERVICE_UNAVAILABLE

  now += 10
  assert target._revoke_capability_session({
    "sid": "session-two", "dep": "deployment-789", "bid": _BOOT_ID,
    "exp": now + 20,
  }) == _revoked_response("session-two")
  assert set(target._REVOKED_SESSIONS) == {"session-two"}


@pytest.mark.parametrize(
  ("overrides", "expected_code"),
  [
    ({"sub": "different-instance"}, "unauthorized"),
    ({"dep": "different-deployment"}, "unauthorized"),
    ({"exp": 1}, "unauthorized"),
    ({"iat": 1_800_000_031, "nbf": 1_800_000_031,
      "exp": 1_800_000_331}, "unauthorized"),
    ({"iat": 1_800_000_000, "nbf": 1_800_000_000,
      "exp": 1_800_003_601}, "unauthorized"),
  ],
)
def test_live_capability_enforces_identity_time_and_lifetime(
  target, monkeypatch, overrides, expected_code,
):
  private_key = _configure_live_capabilities(target)
  monkeypatch.setattr(target.time, "time", lambda: 1_800_000_000)
  token, _claims = _capability_token(
    private_key, now=1_800_000_000, **overrides,
  )
  with pytest.raises(target.RequestError) as denied:
    target._verify_capability_token(token)
  assert denied.value.code == expected_code


def test_live_capability_reports_exact_expiry(target, monkeypatch):
  private_key = _configure_live_capabilities(target)
  token, _claims = _capability_token(
    private_key, now=1_800_000_000, exp=1_800_000_100,
  )
  monkeypatch.setattr(target.time, "time", lambda: 1_800_000_100)
  with pytest.raises(target.RequestError) as expired:
    target._verify_capability_token(token)
  assert expired.value.code == "auth_expired"


def test_probe_and_session_lifetime_boundaries_are_exact(target, monkeypatch):
  now = 1_800_000_000
  private_key = _configure_live_capabilities(target)
  monkeypatch.setattr(target.time, "time", lambda: now)

  for scope, lifetime in (
    ("probe", target.MAX_PROBE_CAPABILITY_LIFETIME_SECONDS),
    ("session", target.MAX_SESSION_CAPABILITY_LIFETIME_SECONDS),
  ):
    token, claims = _capability_token(
      private_key, scope=scope, now=now, exp=now + lifetime,
    )
    assert target._verify_capability_token(token) == claims
    too_long, _claims = _capability_token(
      private_key, scope=scope, now=now, exp=now + lifetime + 1,
    )
    with pytest.raises(target.RequestError) as denied:
      target._verify_capability_token(too_long)
    assert denied.value.code == "unauthorized"


def test_launcher_sized_session_capability_fits_the_wire_limit(target):
  private_key = _configure_live_capabilities(target)
  token, claims = _capability_token(
    private_key,
    sub="mob_" + "a" * 10,
    dep="12345678-1234-1234-1234-123456789abc",
    sid="rec_audit_" + "b" * 32,
  )
  target._LOCAL_INSTANCE_ID = claims["sub"]
  target._LOCAL_DEPLOYMENT_ID = claims["dep"]

  assert len(token.encode("ascii")) <= target.MAX_CAPABILITY_TOKEN_BYTES
  assert target._verify_capability_token(token) == claims


def test_individually_valid_ids_cannot_exceed_aggregate_wire_limit(target):
  private_key = _configure_live_capabilities(target)
  token, _claims = _capability_token(
    private_key, sub="s" * 128, dep="d" * 128, sid="i" * 128,
  )
  assert len(token.encode("ascii")) > target.MAX_CAPABILITY_TOKEN_BYTES

  with pytest.raises(target.RequestError) as denied:
    target._verify_capability_token(token)
  assert denied.value.code == "unauthorized"


def test_live_capability_signature_covers_the_exact_canonical_payload(target):
  private_key = _configure_live_capabilities(target)
  token, _claims = _capability_token(private_key)
  prefix, payload, signature = token.split(".")
  decoded = json.loads(target._base64url_decode_unpadded(
    payload, field="payload",
  ))
  noncanonical = _base64url(
    json.dumps(decoded, sort_keys=False, indent=1).encode("utf-8")
  )
  resigned = private_key.sign(f"{prefix}.{noncanonical}".encode("ascii"))
  malformed = f"{prefix}.{noncanonical}.{_base64url(resigned)}"
  with pytest.raises(target.RequestError) as denied:
    target._verify_capability_token(malformed)
  assert denied.value.code == "unauthorized"

  replacement = "A" if signature[0] != "A" else "B"
  tampered = f"{prefix}.{payload}.{replacement}{signature[1:]}"
  with pytest.raises(target.RequestError) as denied:
    target._verify_capability_token(tampered)
  assert denied.value.code == "unauthorized"


def test_expired_target_rejects_a_valid_bearer_and_closes_listener(
  target, monkeypatch,
):
  target._TARGET_EXPIRES_AT = 1_800_000_000
  monkeypatch.setattr(target.time, "time", lambda: 1_800_000_000)
  with _server(target) as url:
    with pytest.raises(urllib.error.HTTPError) as expired:
      _request(url, "/v1/health")
    assert expired.value.code == 401
    payload = json.load(expired.value)
  assert payload["error"] == {
    "code": "auth_expired",
    "message": "recovery target capability has expired",
  }
  assert target._TARGET_EXPIRED.is_set()
  assert target._STARTUP_TOKEN_DIGEST is None


@pytest.mark.parametrize("raw", [
  "",
  "1800000000.5",
  "-1800000000",
  "1799999999",
  "1800086401",
  "99999999999",
])
def test_target_expiry_must_be_a_future_epoch_within_24_hours(
  target, monkeypatch, raw,
):
  monkeypatch.setattr(target.time, "time", lambda: 1_800_000_000)
  monkeypatch.setenv("MOBIUS_RECOVERY_TARGET_EXPIRES_AT", raw)
  with pytest.raises(RuntimeError):
    target._read_target_expiry()


def test_target_expiry_accepts_the_24_hour_boundary(target, monkeypatch):
  monkeypatch.setattr(target.time, "time", lambda: 1_800_000_000)
  monkeypatch.setenv(
    "MOBIUS_RECOVERY_TARGET_EXPIRES_AT",
    str(1_800_000_000 + target.MAX_TARGET_LIFETIME_SECONDS),
  )
  assert target._read_target_expiry() == 1_800_086_400


def test_listener_falls_back_to_ipv4_when_ipv6_is_unavailable(target, monkeypatch):
  class NoIPv6:
    def __init__(self, *_args, **_kwargs):
      raise OSError(errno.EAFNOSUPPORT, "IPv6 disabled")

  monkeypatch.setattr(target, "_DualStackServer", NoIPv6)
  server = target._create_server(0)
  try:
    assert server.address_family == target.socket.AF_INET
    assert server.server_address[0] == "0.0.0.0"
  finally:
    server.server_close()


def test_request_thread_capacity_is_bounded(target, monkeypatch):
  slots = threading.BoundedSemaphore(1)
  monkeypatch.setattr(target, "_REQUEST_SLOTS", slots)
  monkeypatch.setattr(target, "HEADER_TIMEOUT_SECONDS", 2.0)
  with _server(target) as url:
    port = int(url.rsplit(":", 1)[1])
    held = target.socket.create_connection(("127.0.0.1", port), timeout=2)
    held.sendall(b"GET /v1/health HTTP/1.1\r\nHost: target\r\n")
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
      if not slots.acquire(blocking=False):
        break
      slots.release()
      time.sleep(0.01)
    else:
      raise AssertionError("first request never occupied the bounded slot")

    rejected = target.socket.create_connection(("127.0.0.1", port), timeout=2)
    response = rejected.recv(4096)
    rejected.close()
    assert response.startswith(b"HTTP/1.1 503 Service Unavailable")
    held.close()


def test_partial_headers_have_an_aggregate_deadline_and_release_slot(
  target, monkeypatch,
):
  slots = threading.BoundedSemaphore(1)
  monkeypatch.setattr(target, "_REQUEST_SLOTS", slots)
  monkeypatch.setattr(target, "HEADER_TIMEOUT_SECONDS", 0.15)
  with _server(target) as url:
    port = int(url.rsplit(":", 1)[1])
    stalled = target.socket.create_connection(("127.0.0.1", port), timeout=2)
    started = time.monotonic()
    stalled.sendall(b"GET /v1/health HTTP/1.1\r\nHost: target")
    assert stalled.recv(4096) == b""
    assert time.monotonic() - started < 1
    stalled.close()

    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
      try:
        status, _body = _request(url, "/v1/health")
      except urllib.error.HTTPError as exc:
        if exc.code == 503:
          time.sleep(0.01)
          continue
        raise
      assert status == 200
      break
    else:
      raise AssertionError("header timeout did not release the request slot")


def test_post_auth_body_read_has_a_fixed_deadline(target, monkeypatch):
  monkeypatch.setattr(target, "_REQUEST_SLOTS", threading.BoundedSemaphore(1))
  monkeypatch.setattr(target, "HEADER_TIMEOUT_SECONDS", 1.0)
  monkeypatch.setattr(target, "BODY_TIMEOUT_SECONDS", 0.15)
  with _server(target) as url:
    port = int(url.rsplit(":", 1)[1])
    stalled = target.socket.create_connection(("127.0.0.1", port), timeout=2)
    stalled.sendall(
      b"POST /v1/fs/list HTTP/1.1\r\n"
      b"Host: target\r\n"
      + f"Authorization: Bearer {'t' * 43}\r\n".encode("ascii")
      + b"Content-Type: application/json\r\n"
      b"Content-Length: 100\r\n\r\n{"
    )
    response = _socket_response(stalled)
    stalled.close()
  assert response.startswith(b"HTTP/1.1 408 Request Timeout")


def test_post_auth_body_deadline_is_capped_by_capability_expiry(
  target, monkeypatch, tmp_path,
):
  private_key = _configure_live_capabilities(target)
  _configure_live_attach_gate(target, tmp_path / "attach-ready", ready=True)
  monkeypatch.setattr(target, "_REQUEST_SLOTS", threading.BoundedSemaphore(1))
  monkeypatch.setattr(target, "HEADER_TIMEOUT_SECONDS", 1.0)
  monkeypatch.setattr(target, "BODY_TIMEOUT_SECONDS", 10.0)
  now = int(time.time())
  token, _claims = _capability_token(
    private_key, now=now, exp=now + 2,
  )
  with _server(target) as url:
    port = int(url.rsplit(":", 1)[1])
    stalled = target.socket.create_connection(("127.0.0.1", port), timeout=4)
    started = time.monotonic()
    stalled.sendall(
      b"POST /v1/fs/list HTTP/1.1\r\n"
      b"Host: target\r\n"
      + f"Authorization: Bearer {token}\r\n".encode("ascii")
      + b"Content-Type: application/json\r\n"
      b"Content-Length: 100\r\n\r\n{"
    )
    response = _socket_response(stalled)
    elapsed = time.monotonic() - started
    stalled.close()
  assert response.startswith(b"HTTP/1.1 401 Unauthorized")
  assert b'"code":"auth_expired"' in response
  assert elapsed < 3


def test_exec_uses_argv_without_shell_and_does_not_inherit_target_token(
  target, tmp_path,
):
  result = target._run_exec({
    "argv": [
      "/bin/sh", "-c",
      "printf '%s' \"$GREETING\"; test -z \"$MOBIUS_RECOVERY_TARGET_TOKEN\"",
    ],
    "cwd": str(tmp_path),
    "env": {"GREETING": "hello"},
  })
  assert result["exit_code"] == 0
  assert "stdout" not in result
  assert "stderr" not in result
  assert base64.b64decode(result["stdout_base64"]) == b"hello"
  assert result["timed_out"] is False
  assert result["truncated"] is False


def test_exec_timeout_kills_the_process_group(target, tmp_path):
  started = time.monotonic()
  result = target._run_exec({
    "argv": ["/bin/sh", "-c", "sleep 30 & wait"],
    "cwd": str(tmp_path),
    "timeout_seconds": 0.1,
  })
  assert result["timed_out"] is True
  assert result["exit_code"] != 0
  assert time.monotonic() - started < 3


def test_live_capability_expiry_kills_an_inflight_exec_tree(target, tmp_path):
  _configure_live_capabilities(target)
  marker = tmp_path / "capability-command.pid"
  # Ceil to the next second, then allow one complete second so the command is
  # definitely in flight before the integer epoch capability expires.
  expires_at = int(time.time()) + 2
  started = time.monotonic()
  with pytest.raises(target.RequestError) as expired:
    target._run_exec({
      "argv": [
        "/bin/sh", "-c", f"echo $$ > {marker}; exec sleep 30",
      ],
      "cwd": str(tmp_path),
      "timeout_seconds": 10,
    }, capability_expires_at=expires_at)
  assert expired.value.code == "auth_expired"
  assert time.monotonic() - started < 4
  assert marker.exists()
  command_pid = int(marker.read_text())
  assert not Path(f"/proc/{command_pid}").exists()


def test_exec_supervisor_kills_and_reaps_setsid_double_fork(
  target, tmp_path,
):
  marker = tmp_path / "escaped.pid"
  program = f'''
import os
import time

pid = os.fork()
if pid:
  os._exit(0)
os.setsid()
pid = os.fork()
if pid:
  os._exit(0)
with open({str(marker)!r}, "w", encoding="ascii") as target:
  target.write(str(os.getpid()))
time.sleep(30)
'''
  started = time.monotonic()
  result = target._run_exec({
    "argv": [sys.executable, "-c", program],
    "cwd": str(tmp_path),
    "timeout_seconds": 5,
  })

  assert result["exit_code"] == 0
  assert result["timed_out"] is False
  assert time.monotonic() - started < 3
  escaped_pid = int(marker.read_text())
  assert not Path(f"/proc/{escaped_pid}").exists()


def test_exec_supervisor_kills_detached_child_that_closes_output_pipes(
  target, tmp_path,
):
  marker = tmp_path / "detached.pid"
  program = f'''
import os
import time

pid = os.fork()
if pid:
  os._exit(0)
os.setsid()
for fd in (0, 1, 2):
  try:
    os.close(fd)
  except OSError:
    pass
with open({str(marker)!r}, "w", encoding="ascii") as target:
  target.write(str(os.getpid()))
time.sleep(30)
'''
  result = target._run_exec({
    "argv": [sys.executable, "-c", program],
    "cwd": str(tmp_path),
    "timeout_seconds": 5,
  })

  assert result["exit_code"] == 0
  escaped_pid = int(marker.read_text())
  assert not Path(f"/proc/{escaped_pid}").exists()


def test_concurrent_exec_cleanup_does_not_kill_an_active_supervisor(
  target, tmp_path,
):
  ready = tmp_path / "long-command.ready"
  long_program = f'''
import pathlib
import time

pathlib.Path({str(ready)!r}).touch()
time.sleep(0.5)
print("survived")
'''
  with ThreadPoolExecutor(max_workers=2) as executor:
    long_result = executor.submit(target._run_exec, {
      "argv": [sys.executable, "-c", long_program],
      "cwd": str(tmp_path),
      "timeout_seconds": 5,
    })
    deadline = time.monotonic() + 3
    while not ready.exists() and time.monotonic() < deadline:
      time.sleep(0.01)
    assert ready.exists(), "long-running supervisor never became active"
    short_result = executor.submit(target._run_exec, {
      "argv": ["/bin/true"],
      "cwd": str(tmp_path),
      "timeout_seconds": 5,
    })

  assert short_result.result()["exit_code"] == 0
  completed = long_result.result()
  assert completed["exit_code"] == 0
  assert base64.b64decode(completed["stdout_base64"]) == b"survived\n"


def test_exec_output_is_bounded_and_process_is_killed(target, tmp_path, monkeypatch):
  monkeypatch.setattr(target, "MAX_OUTPUT_BYTES", 1024)
  result = target._run_exec({
    "argv": ["/bin/sh", "-c", "yes x"],
    "cwd": str(tmp_path),
    "timeout_seconds": 5,
  })
  assert result["truncated"] is True
  assert len(base64.b64decode(result["stdout_base64"])) == 1024
  assert result["exit_code"] != 0


def test_file_read_write_and_list_protocol(target, tmp_path):
  path = tmp_path / "payload.bin"
  status = target._write_file({
    "path": str(path),
    "data_base64": base64.b64encode(b"abcdef").decode(),
    "mode": 0o640,
  })
  assert status["bytes_written"] == 6
  assert path.read_bytes() == b"abcdef"
  assert path.stat().st_mode & 0o777 == 0o640

  first = target._read_file({"path": str(path), "offset": 1, "limit": 3})
  assert base64.b64decode(first["data_base64"]) == b"bcd"
  assert first["eof"] is False
  listing = target._list_directory({"path": str(tmp_path)})
  assert [(item["name"], item["type"]) for item in listing["entries"]] == [
    ("payload.bin", "file")
  ]


def test_file_endpoints_work_over_http(target, tmp_path):
  path = tmp_path / "network.txt"
  with _server(target) as url:
    status, write = _request(url, "/v1/fs/write", body={
      "path": str(path),
      "data_base64": base64.b64encode(b"network").decode(),
    })
    assert status == 200
    assert write["bytes_written"] == 7
    _, read = _request(url, "/v1/fs/read", body={"path": str(path)})
    assert base64.b64decode(read["data_base64"]) == b"network"


@pytest.mark.parametrize("path", [
  "/proc/1/maps",
  "/proc/1/mem",
  "/proc/1/environ",
  "/sys/kernel",
  "/dev/null",
  "/etc/passwd",
])
def test_file_api_rejects_paths_outside_explicit_recovery_roots(target, path):
  operations = (
    (target._read_file, {"path": path}),
    (target._list_directory, {"path": path}),
    (target._write_file, {
      "path": path,
      "data_base64": base64.b64encode(b"blocked").decode("ascii"),
    }),
  )
  for operation, body in operations:
    with pytest.raises(target.RequestError) as denied:
      operation(body)
    assert denied.value.code == "path_forbidden"
    assert denied.value.status == target.HTTPStatus.FORBIDDEN


def test_file_api_rejects_dotdot_and_symlink_escapes(target, tmp_path):
  proc_link = tmp_path / "proc-link"
  proc_link.symlink_to("/proc", target_is_directory=True)
  attempts = (
    (target._read_file, {"path": "/tmp/../proc/1/maps"}),
    (target._read_file, {"path": str(proc_link / "1" / "maps")}),
    (target._list_directory, {"path": str(proc_link / "1")}),
    (target._write_file, {
      "path": str(proc_link / "forbidden"),
      "data_base64": base64.b64encode(b"blocked").decode("ascii"),
    }),
  )
  for operation, body in attempts:
    with pytest.raises(target.RequestError) as denied:
      operation(body)
    assert denied.value.code == "path_forbidden"


def test_file_api_preserves_relative_symlinks_within_one_allowed_mount(
  target, tmp_path,
):
  real = tmp_path / "real"
  real.mkdir()
  (real / "existing").write_bytes(b"safe")
  link = tmp_path / "internal-link"
  link.symlink_to("real", target_is_directory=True)

  read = target._read_file({"path": str(link / "existing")})
  assert base64.b64decode(read["data_base64"]) == b"safe"
  target._write_file({
    "path": str(link / "created"),
    "data_base64": base64.b64encode(b"written").decode("ascii"),
  })
  assert (real / "created").read_bytes() == b"written"


def test_openat2_rejects_cross_mount_resolution(target):
  root_fd = os.open("/", os.O_PATH | os.O_DIRECTORY)
  try:
    with pytest.raises(OSError) as denied:
      target._openat2(root_fd, Path("proc/1/maps"), os.O_RDONLY)
  finally:
    os.close(root_fd)
  assert denied.value.errno == errno.EXDEV


def test_target_startup_fails_closed_without_openat2(target, monkeypatch):
  def unavailable(*_args, **_kwargs):
    raise OSError(errno.ENOSYS, "openat2 unavailable")

  monkeypatch.setattr(target, "_openat2", unavailable)
  with pytest.raises(RuntimeError, match="filesystem policy is unavailable"):
    target._assert_fs_policy_supported()


def test_exact_eight_mib_file_write_fits_wire_budget(target, tmp_path):
  payload = b"w" * target.MAX_FILE_BYTES
  path = tmp_path / "boundary.bin"
  with _server(target) as url:
    status, write = _request(url, "/v1/fs/write", body={
      "path": str(path),
      "data_base64": base64.b64encode(payload).decode("ascii"),
    })
  assert status == 200
  assert write["bytes_written"] == 8 * 1024 * 1024
  assert path.stat().st_size == 8 * 1024 * 1024


def test_exact_eight_mib_exec_stdin_fits_wire_budget(target, tmp_path):
  payload = b"s" * target.MAX_FILE_BYTES
  with _server(target) as url:
    status, result = _request(url, "/v1/exec", body={
      "argv": ["/bin/sh", "-c", "wc -c"],
      "cwd": str(tmp_path),
      "stdin_base64": base64.b64encode(payload).decode("ascii"),
    })
  assert status == 200
  assert result["exit_code"] == 0
  assert int(base64.b64decode(result["stdout_base64"]).strip()) == 8 * 1024 * 1024


def test_request_wire_budget_rejects_more_than_twelve_mib(target):
  assert target.MAX_REQUEST_BYTES == 12 * 1024 * 1024
  handler = object.__new__(target._Handler)
  handler.headers = {
    "Content-Length": str(target.MAX_REQUEST_BYTES + 1),
  }
  handler.rfile = io.BytesIO(b"")
  with pytest.raises(target.RequestError) as too_large:
    handler._body()
  assert too_large.value.code == "payload_too_large"
  assert too_large.value.status == target.HTTPStatus.REQUEST_ENTITY_TOO_LARGE


def test_exec_environment_has_an_aggregate_byte_budget(target, tmp_path):
  assert target.MAX_ENV_BYTES == 256 * 1024
  with pytest.raises(target.RequestError) as too_large:
    target._run_exec({
      "argv": ["/bin/true"],
      "cwd": str(tmp_path),
      "env": {
        "A": "a" * (64 * 1024),
        "B": "b" * (64 * 1024),
        "C": "c" * (64 * 1024),
        "D": "d" * (64 * 1024),
      },
    })
  assert too_large.value.code == "invalid_request"
  assert "aggregate" in too_large.value.message


def test_directory_listing_has_an_aggregate_response_budget(
  target, tmp_path, monkeypatch,
):
  (tmp_path / "long-link").symlink_to("x" * 512)
  monkeypatch.setattr(target, "MAX_LIST_RESPONSE_BYTES", 128)
  with pytest.raises(target.RequestError) as too_large:
    target._list_directory({"path": str(tmp_path)})
  assert too_large.value.code == "response_too_large"


@pytest.mark.parametrize("value", ["", "short", "x" * 513])
def test_target_token_fails_closed(target, value):
  with pytest.raises(RuntimeError, match="32-512"):
    target._validate_token(value.encode("utf-8"))


def test_direct_secret_environment_is_rejected(target, monkeypatch):
  monkeypatch.setenv("MOBIUS_RECOVERY_TARGET_TOKEN", "s" * 43)
  with pytest.raises(RuntimeError, match="must not reach"):
    target._read_startup_token_digest()


def test_live_public_key_is_raw_unpadded_base64url_and_consumed(
  target, monkeypatch,
):
  private_key = Ed25519PrivateKey.generate()
  raw = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
  )
  encoded = _base64url(raw)
  assert "=" not in encoded
  monkeypatch.setenv(target.CAPABILITY_PUBLIC_KEY_ENV, encoded)
  loaded = target._read_capability_public_key()
  signature = private_key.sign(b"probe")
  loaded.verify(signature, b"probe")
  assert target.CAPABILITY_PUBLIC_KEY_ENV not in os.environ


@pytest.mark.parametrize(
  "value",
  ("", "short", "A" * 31, "A" * 33, "A" * 31 + "!"),
)
def test_live_boot_id_is_exact_base64url_and_consumed(target, monkeypatch, value):
  monkeypatch.setenv(target.BOOT_ID_ENV, value)
  with pytest.raises(RuntimeError, match="32-character base64url"):
    target._read_boot_id()


def test_live_boot_id_accepts_entrypoint_generated_grammar(target, monkeypatch):
  monkeypatch.setenv(target.BOOT_ID_ENV, _BOOT_ID)
  assert target._read_boot_id() == _BOOT_ID
  assert target.BOOT_ID_ENV not in os.environ


@pytest.mark.parametrize("missing", ["MOBIUS_INSTANCE_ID", "RAILWAY_DEPLOYMENT_ID"])
def test_live_security_initialization_requires_both_local_identities(
  target, monkeypatch, missing,
):
  private_key = Ed25519PrivateKey.generate()
  raw = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
  )
  monkeypatch.setenv(target.CAPABILITY_PUBLIC_KEY_ENV, _base64url(raw))
  monkeypatch.setenv("MOBIUS_INSTANCE_ID", "instance-123")
  monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "deployment-789")
  monkeypatch.delenv(missing)
  monkeypatch.setattr(target, "_assert_clean_initial_environment", lambda: None)
  monkeypatch.setattr(target, "_assert_fs_policy_supported", lambda: None)
  monkeypatch.setattr(target, "_drop_recovery_escape_capabilities", lambda: None)
  monkeypatch.setattr(target, "_set_process_nondumpable", lambda: None)
  monkeypatch.setattr(target, "_set_child_subreaper", lambda: None)
  monkeypatch.setattr(target, "_load_baked_build_revision", lambda: "a" * 40)
  with pytest.raises(RuntimeError, match=f"{missing} is required"):
    target._initialize_startup_security(
      require_pid_one=False, auth_mode="capability",
    )


@pytest.mark.parametrize("suffix", ["=", "!", "A"])
def test_live_public_key_rejects_noncanonical_or_wrong_length(
  target, monkeypatch, suffix,
):
  encoded = _base64url(b"k" * 32) + suffix
  monkeypatch.setenv(target.CAPABILITY_PUBLIC_KEY_ENV, encoded)
  with pytest.raises(RuntimeError, match="32-byte Ed25519"):
    target._read_capability_public_key()


def test_target_retains_only_a_one_way_bearer_verifier(target):
  raw = b"t" * 43
  assert not hasattr(target, "_STARTUP_TOKEN")
  assert target._STARTUP_TOKEN_DIGEST == target._token_digest(raw)
  assert len(target._STARTUP_TOKEN_DIGEST) == 32
  assert target._STARTUP_TOKEN_DIGEST != raw


def test_fd_secret_is_absent_from_target_and_root_exec_proc_environments(
  tmp_path,
):
  """Exercise the real fd handoff, prctl, /proc, and exec boundary."""
  token = b"subprocess-only-secret-" + b"z" * 43
  revision = tmp_path / "BUILD_REVISION"
  revision.write_text("a" * 40 + "\n")
  read_fd, write_fd = os.pipe()
  try:
    os.write(write_fd, token)
  finally:
    os.close(write_fd)
  env = os.environ.copy()
  env.pop("MOBIUS_RECOVERY_TARGET_TOKEN", None)
  env["MOBIUS_RECOVERY_TARGET_TOKEN_FD"] = str(read_fd)
  env["MOBIUS_RECOVERY_TARGET_EXPIRES_AT"] = str(int(time.time()) + 3600)
  program = r'''
import base64
import ctypes
import importlib.util
import json
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("subprocess_targetd", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.BUILD_REVISION_PATH = Path(sys.argv[2])
module._drop_recovery_escape_capabilities = lambda: None
module._initialize_startup_security(require_pid_one=False)
dumpable = ctypes.CDLL(None, use_errno=True).prctl(3, 0, 0, 0, 0)
try:
  self_environment = Path("/proc/self/environ").read_bytes()
  self_environment_blocked = False
except PermissionError:
  self_environment = b""
  self_environment_blocked = True
parent_pid = os.getpid()
result = module._run_exec({
  "argv": [
    "/bin/sh", "-c",
    f"cat /proc/self/environ; cat /proc/{parent_pid}/environ",
  ],
  "cwd": "/tmp",
})
print(json.dumps({
  "self_environment": base64.b64encode(self_environment).decode("ascii"),
  "self_environment_blocked": self_environment_blocked,
  "dumpable": dumpable,
  "fd_closed": not Path(f"/proc/self/fd/{sys.argv[3]}").exists(),
  "exec": result,
}))
'''
  try:
    completed = subprocess.run(
      [
        sys.executable, "-c", program, str(_TARGET_PATH), str(revision),
        str(read_fd),
      ],
      env=env,
      pass_fds=(read_fd,),
      text=True,
      capture_output=True,
      timeout=15,
    )
  finally:
    os.close(read_fd)
  assert completed.returncode == 0, completed.stderr
  assert token.decode("ascii") not in completed.stdout
  assert token.decode("ascii") not in completed.stderr
  payload = json.loads(completed.stdout)
  own_environment = base64.b64decode(payload["self_environment"])
  command_stdout = base64.b64decode(payload["exec"]["stdout_base64"])
  assert token not in own_environment
  assert b"MOBIUS_RECOVERY_TARGET_TOKEN=" not in own_environment
  assert token not in command_stdout
  assert b"MOBIUS_RECOVERY_TARGET_TOKEN=" not in command_stdout
  assert b"MOBIUS_RECOVERY_TARGET_EXPIRES_AT=" not in command_stdout
  # Root can read its own /proc/self/environ on some kernels even after
  # PR_SET_DUMPABLE=0. The security boundary is that the target is provably
  # non-dumpable and its root exec child cannot inspect the parent; the real
  # container drill below proves the same invariant across pid 1.
  assert payload["dumpable"] == 0
  assert payload["fd_closed"] is True
  assert payload["exec"]["exit_code"] != 0


def test_escape_capabilities_are_removed_from_all_sets_and_bounding(
  target, monkeypatch,
):
  blocked = set(target._BLOCKED_CAPABILITIES)
  data = (target._CapabilityData * 2)()
  for capability in blocked:
    mask = 1 << (capability % 32)
    data[capability // 32].effective |= mask
    data[capability // 32].permitted |= mask
    data[capability // 32].inheritable |= mask
  bounding = set(blocked)
  ambient = set(blocked)

  class FakeLibc:
    def capget(self, _header, _data):
      return 0

    def capset(self, _header, _data):
      return 0

    def prctl(self, operation, argument, *_unused):
      if operation == target._PR_CAPBSET_READ:
        return int(argument in bounding)
      if operation == target._PR_CAPBSET_DROP:
        bounding.discard(argument)
        return 0
      if (
        operation == target._PR_CAP_AMBIENT
        and argument == target._PR_CAP_AMBIENT_CLEAR_ALL
      ):
        ambient.clear()
        return 0
      if operation == target._PR_CAP_AMBIENT:
        capability = _unused[0]
        return int(capability in ambient)
      raise AssertionError((operation, argument, _unused))

  fake_libc = FakeLibc()
  monkeypatch.setattr(target.ctypes, "CDLL", lambda *_args, **_kwargs: fake_libc)
  monkeypatch.setattr(
    target,
    "_capability_state",
    lambda _libc: (target._CapabilityHeader(), data),
  )

  target._drop_recovery_escape_capabilities()

  assert bounding == set()
  assert ambient == set()
  for capability in blocked:
    mask = 1 << (capability % 32)
    word = data[capability // 32]
    assert not word.effective & mask
    assert not word.permitted & mask
    assert not word.inheritable & mask


def test_health_identity_is_baked_not_runtime_environment(
  target, monkeypatch,
):
  monkeypatch.setenv("BUILD_SHA", "runtime-spoof")
  target._BUILD_REVISION = "b" * 40
  with _server(target) as url:
    _, body = _request(url, "/v1/health")
  assert body["build_sha"] == "b" * 40


def test_paths_must_be_absolute(target):
  with pytest.raises(target.RequestError, match="absolute"):
    target._read_file({"path": "relative"})


def test_request_body_and_file_bounds_are_explicit(target, monkeypatch, tmp_path):
  monkeypatch.setattr(target, "MAX_FILE_BYTES", 4)
  with pytest.raises(target.RequestError) as too_large:
    target._write_file({
      "path": str(tmp_path / "large"),
      "data_base64": base64.b64encode(b"12345").decode(),
    })
  assert too_large.value.code == "payload_too_large"


def test_entrypoint_attaches_live_target_without_replacing_normal_boot():
  entrypoint = (
    Path(__file__).resolve().parents[1] / "scripts" / "entrypoint.sh"
  ).read_text(encoding="utf-8")
  data_init = entrypoint.index("mkdir -p /data/db")
  live_start = entrypoint.index(
    "python3 -I /app/recovery-target/targetd.py &", data_init,
  )
  normal_app = entrypoint.index("exec su -s /bin/sh mobius -c")
  assert data_init < live_start < normal_app
  assert "MOBIUS_BOOT_MODE=recovery" not in entrypoint[data_init:live_start]


def test_live_target_child_environment_excludes_empty_legacy_variables():
  entrypoint = (
    Path(__file__).resolve().parents[1] / "scripts" / "entrypoint.sh"
  ).read_text(encoding="utf-8")
  start = entrypoint.index("    env -i ")
  end = entrypoint.index(
    "python3 -I /app/recovery-target/targetd.py &", start,
  )
  command = entrypoint[start:end]
  assert "MOBIUS_BOOT_MODE=normal" in command
  assert "MOBIUS_INSTANCE_ID" in command
  assert "RAILWAY_DEPLOYMENT_ID" in command
  for legacy in (
    "MOBIUS_RECOVERY_TARGET_TOKEN",
    "MOBIUS_RECOVERY_TARGET_TOKEN_FD",
    "MOBIUS_RECOVERY_TARGET_EXPIRES_AT",
  ):
    assert legacy not in command


def test_live_target_failure_or_port_conflict_never_blocks_normal_app():
  entrypoint = (
    Path(__file__).resolve().parents[1] / "scripts" / "entrypoint.sh"
  ).read_text(encoding="utf-8")
  start = entrypoint.index("# When the launcher provisions its Ed25519 verifier")
  end = entrypoint.index("# Retire embedded-recovery authority", start)
  block = entrypoint[start:end]
  assert "MOBIUS_RECOVERY_CAPABILITY_PUBLIC_KEY" in block
  assert "MOBIUS_RECOVERY_TARGET_PORT" in block
  assert "${PORT:-8000}" in block
  assert "MOBIUS_PORT" in block
  assert "normal Möbius boot will continue" in block
  assert "exit " not in block


def test_entrypoint_never_waits_for_or_infers_live_target_readiness():
  entrypoint = (
    Path(__file__).resolve().parents[1] / "scripts" / "entrypoint.sh"
  ).read_text(encoding="utf-8")
  start = entrypoint.index("# When the launcher provisions its Ed25519 verifier")
  end = entrypoint.index("# Retire embedded-recovery authority", start)
  block = entrypoint[start:end]
  assert "MOBIUS_RECOVERY_ATTACH_READY_FILE" in block
  assert "MOBIUS_RECOVERY_BOOT_ID" in block
  assert "MOBIUS_RECOVERY_APP_READY_FILE" not in block
  assert "MOBIUS_RECOVERY_TARGET_READY_FILE" not in block
  assert "/v1/health" not in block
  assert " wait " not in block
  assert "python3 -I /app/recovery-target/targetd.py &" in block


def test_entrypoint_releases_attach_gate_after_init_without_app_health():
  entrypoint = (
    Path(__file__).resolve().parents[1] / "scripts" / "entrypoint.sh"
  ).read_text(encoding="utf-8")
  target_start = entrypoint.index(
    "python3 -I /app/recovery-target/targetd.py &",
  )
  probe = entrypoint.index('if curl -sf "$_health_url"')
  start_command = entrypoint.index('_uvicorn_flags="')
  publish = entrypoint.index(
    '> "$_live_recovery_attach_ready_file"', start_command,
  )
  app_start = entrypoint.index("exec su -s /bin/sh mobius -c")
  assert target_start < probe < start_command < publish < app_start
  health_probe = entrypoint[
    probe:entrypoint.index(") &", probe) + len(") &")
  ]
  assert "_live_recovery_attach_ready_file" not in health_probe
  assert "printf 'ready:%s\\n' \"$_live_recovery_boot_id\"" in entrypoint
