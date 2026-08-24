from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import httpx
import pytest


BROKER_PATH = Path(__file__).parents[1] / "runtime" / "identity_broker.py"
ENTRYPOINT_PATH = Path(__file__).parents[1] / "scripts" / "entrypoint.sh"
SPEC = importlib.util.spec_from_file_location("mobius_identity_broker", BROKER_PATH)
assert SPEC and SPEC.loader
broker_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(broker_module)


def test_entrypoint_preserves_managed_identity_credential():
  source = ENTRYPOINT_PATH.read_text()
  assert "unset MOBIUS_COMPUTE_INSTANCE_TOKEN" in source
  assert "unset MOBIUS_SSO_CLIENT_SECRET" not in source


@pytest.fixture()
def broker(tmp_path, monkeypatch):
  private = tmp_path / "identity-broker"
  monkeypatch.setattr(broker_module, "PRIVATE_DIR", private)
  monkeypatch.setattr(broker_module, "KEY_PATH", private / "instance-ed25519.pem")
  monkeypatch.setattr(broker_module, "STATE_PATH", private / "identity.json")
  monkeypatch.setattr(broker_module, "INSTANCE_PATH", private / "instance-id")
  monkeypatch.setattr(
    broker_module, "PENDING_BOOTSTRAP_PATH", private / "pending-enrollment.jwt"
  )
  monkeypatch.setattr(
    broker_module, "OAUTH_STATE_PATH", private / "oauth-states.json"
  )
  monkeypatch.setattr(broker_module.os, "chown", lambda *_args: None)
  monkeypatch.delenv("MOBIUS_SSO_INSTANCE_ID", raising=False)
  value = broker_module.Broker()
  yield value
  value.close()


def test_private_key_and_identity_state_stay_root_only(broker):
  key_mode = stat.S_IMODE(broker_module.KEY_PATH.stat().st_mode)
  private_mode = stat.S_IMODE(broker_module.PRIVATE_DIR.stat().st_mode)

  assert key_mode == 0o600
  assert private_mode == 0o700
  public = broker.identity()
  assert public["linked"] is False
  assert set(public) == {
    "linked", "issuer", "subject", "instance_id", "key_generation",
    "public_key_jwk", "key_thumbprint",
  }
  assert "private" not in json.dumps(public).lower()


def test_private_directory_and_key_reject_precreated_symlinks(tmp_path, monkeypatch):
  private_target = tmp_path / "attacker-controlled"
  private_target.mkdir()
  private_link = tmp_path / "identity-broker-link"
  private_link.symlink_to(private_target, target_is_directory=True)
  monkeypatch.setattr(broker_module, "PRIVATE_DIR", private_link)

  with pytest.raises(RuntimeError, match="private directory is unsafe"):
    broker_module._prepare_private_dir()

  private = tmp_path / "identity-broker"
  private.mkdir(mode=0o700)
  outside_key = tmp_path / "known-key.pem"
  outside_key.write_text("attacker chosen")
  key_link = private / "instance-ed25519.pem"
  key_link.symlink_to(outside_key)
  monkeypatch.setattr(broker_module, "PRIVATE_DIR", private)
  monkeypatch.setattr(broker_module, "KEY_PATH", key_link)

  with pytest.raises(RuntimeError, match="file is unsafe"):
    broker_module._load_or_create_key()


def test_socket_parent_must_not_be_app_writable(tmp_path, monkeypatch):
  unsafe = tmp_path / "run"
  unsafe.mkdir(mode=0o777)
  unsafe.chmod(0o777)
  monkeypatch.setattr(
    broker_module, "SOCKET_PATH", unsafe / "mobius-identity-broker.sock"
  )

  with pytest.raises(RuntimeError, match="socket directory is unsafe"):
    broker_module._prepare_socket_dir()


def test_unlink_clears_only_matching_identity_and_keeps_instance_keys(broker):
  state = {
    "issuer": "https://www.mobius.you",
    "subject": "user_example",
    "instance_id": broker.instance_id,
    "key_thumbprint": broker.thumbprint(),
    "key_generation": 1,
  }
  broker_module._atomic_root_write(
    broker_module.STATE_PATH,
    json.dumps(state, separators=(",", ":")).encode(),
  )
  broker.state = state
  key_before = broker_module.KEY_PATH.read_bytes()
  instance_before = broker.instance_id

  with pytest.raises(PermissionError):
    broker.unlink("another_user")
  assert broker.identity()["linked"] is True
  assert broker_module.STATE_PATH.exists()

  unlinked = broker.unlink("user_example")
  assert unlinked["linked"] is False
  assert not broker_module.STATE_PATH.exists()
  assert broker_module.KEY_PATH.read_bytes() == key_before
  assert broker.instance_id == instance_before


def _unsigned_receipt(instance_id, *, expires_in=600):
  header = broker_module._b64(b'{"alg":"HS256","typ":"JWT"}')
  payload = broker_module._b64(json.dumps({
    "instance_id": instance_id,
    "jti": "receipt_test_123456789",
    "exp": int(time.time()) + expires_in,
  }).encode())
  return f"{header}.{payload}.signature"


def test_transient_bootstrap_is_root_persisted_and_survives_restart(
  broker, monkeypatch,
):
  receipt = _unsigned_receipt(broker.instance_id)
  broker.queue_bootstrap(receipt)
  assert broker_module.PENDING_BOOTSTRAP_PATH.read_text() == receipt
  assert stat.S_IMODE(broker_module.PENDING_BOOTSTRAP_PATH.stat().st_mode) == 0o600

  monkeypatch.setattr(
    broker, "enroll", lambda _receipt: (_ for _ in ()).throw(httpx.ConnectError("down"))
  )
  assert broker.retry_pending_once() is False
  assert broker_module.PENDING_BOOTSTRAP_PATH.exists()

  # A fresh broker process loads the same root key/instance and can consume the
  # still-pending receipt after the central service recovers.
  restarted = broker_module.Broker()
  try:
    def recovered(_receipt):
      restarted.state = {
        "issuer": "https://www.mobius.you",
        "subject": "user_example",
        "instance_id": restarted.instance_id,
        "key_thumbprint": restarted.thumbprint(),
        "key_generation": 1,
      }
      return restarted.identity()

    monkeypatch.setattr(restarted, "enroll", recovered)
    assert restarted.retry_pending_once() is True
    assert not broker_module.PENDING_BOOTSTRAP_PATH.exists()
  finally:
    restarted.close()


def test_browser_oauth_state_is_root_persisted_multi_worker_safe_and_single_use(broker):
  state = "state_" + ("x" * 40)
  value = {
    "state": state,
    "owner": "owner",
    "verifier": "verifier_" + ("v" * 40),
    "instance_id": broker.instance_id,
    "public_key_jwk": broker.public_jwk(),
    "redirect_uri": "https://example.test/api/auth/provider/mobius/callback",
    "expires_at": time.time() + 300,
  }
  broker.save_oauth_state(value)
  assert stat.S_IMODE(broker_module.OAUTH_STATE_PATH.stat().st_mode) == 0o600

  # A second broker object represents another backend worker/process using the
  # same root-owned state boundary.
  other_worker = broker_module.Broker()
  try:
    assert other_worker.consume_oauth_state(state) == value
    assert broker.consume_oauth_state(state) is None
  finally:
    other_worker.close()


def test_mobius_uid_cannot_read_broker_files_or_root_process_environment(broker):
  if os.geteuid() != 0:
    pytest.skip("requires root to exercise the production UID boundary")
  if subprocess.run(
    ["id", "mobius"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
  ).returncode:
    pytest.skip("production mobius user is not installed")
  broker_module._atomic_root_write(broker_module.STATE_PATH, b'{"linked":true}')
  for protected in (broker_module.KEY_PATH, broker_module.STATE_PATH):
    result = subprocess.run(
      ["runuser", "-u", "mobius", "--", "cat", str(protected)],
      capture_output=True,
    )
    assert result.returncode != 0

  process = subprocess.Popen(
    ["python3", "-c", "import time; time.sleep(10)"],
    env={**os.environ, "MOBIUS_TEST_DURABLE_SECRET": "must-not-leak"},
  )
  try:
    result = subprocess.run(
      ["runuser", "-u", "mobius", "--", "cat", f"/proc/{process.pid}/environ"],
      capture_output=True,
    )
    assert b"must-not-leak" not in result.stdout
    assert result.returncode != 0
  finally:
    process.terminate()
    process.wait(timeout=5)


def test_loopback_surface_cannot_reach_identity_contribution_or_generic_targets(
  broker, monkeypatch,
):
  monkeypatch.setattr(broker, "_capability", lambda **_kwargs: "capability")

  with pytest.raises(FileNotFoundError):
    broker.proxy(
      method="POST", path="/v1/contributions", body=b"{}", headers={},
      allow_contributions=False,
    )
  with pytest.raises(FileNotFoundError):
    broker.proxy(
      method="POST", path="/v1/chat/completions", body=b"{}", headers={},
      allow_contributions=False,
    )
  with pytest.raises(FileNotFoundError):
    broker.proxy(
      method="GET", path="/identity", body=b"", headers={},
      allow_contributions=False,
    )


def test_proxy_uses_streaming_httpx_send_and_never_forwards_caller_target(
  broker, monkeypatch,
):
  seen = {}

  class FakeClient:
    def build_request(self, method, url, **kwargs):
      seen["method"] = method
      seen["url"] = url
      seen["kwargs"] = kwargs
      return httpx.Request(method, url, content=kwargs.get("content"), headers=kwargs["headers"])

    def send(self, request, *, stream):
      seen["stream"] = stream
      return httpx.Response(
        200, request=request, stream=httpx.ByteStream(b"event: done\n\n")
      )

    def close(self):
      return None

  broker.client.close()
  broker.client = FakeClient()
  broker.state = {
    "issuer": "https://www.mobius.you",
    "subject": "user_example",
    "key_generation": 1,
  }
  monkeypatch.setattr(broker, "_capability", lambda **_kwargs: "one-use")
  response = broker.proxy(
    method="GET", path="/v1/models", body=b"",
    headers={"x-forwarded-host": "attacker.example"},
    allow_contributions=False,
  )
  try:
    assert seen["url"] == broker_module.GATEWAY_BASE_URL + "/v1/models"
    assert seen["stream"] is True
    assert "attacker.example" not in json.dumps(seen)
    assert response.read() == b"event: done\n\n"
  finally:
    response.close()


def test_gateway_capability_wraps_the_exact_signed_request_binding(broker):
  seen = {}

  def handler(request: httpx.Request):
    seen["request"] = request
    return httpx.Response(200, json={"capability": "header.payload.signature"})

  broker.client.close()
  broker.client = httpx.Client(transport=httpx.MockTransport(handler))
  broker.state = {
    "issuer": "https://www.mobius.you",
    "subject": "user_example",
    "key_generation": 7,
  }
  body = b'{"model":"inkling","input":"hello"}'

  assert broker._capability(
    audience="mobius-agent-gateway",
    scope="inference:responses",
    method="POST",
    path="/v1/responses",
    body=body,
    request_id="turn:12345678",
  ) == "header.payload.signature"

  request = seen["request"]
  assert request.url == httpx.URL(
    broker_module.IDENTITY_BASE_URL + "/identity/capabilities"
  )
  payload = json.loads(request.content)
  assert set(payload) == {"assertion"}
  envelope = payload["assertion"]
  claims = envelope["claims"]
  assert claims["aud"] == "mobius-agent-gateway"
  assert claims["scope"] == "inference:responses"
  assert claims["method"] == "POST"
  assert claims["path"] == "/v1/responses"
  assert claims["body_sha256"] == hashlib.sha256(body).hexdigest()
  assert claims["request_id"] == "turn:12345678"
  canonical = json.dumps(
    claims, sort_keys=True, separators=(",", ":")
  ).encode()
  broker.key.public_key().verify(
    broker_module._unb64(envelope["signature"]), canonical,
  )


def test_contribution_proxy_binds_and_forwards_idempotency_key(broker, monkeypatch):
  seen = {}

  class FakeClient:
    def build_request(self, method, url, **kwargs):
      seen["url"] = url
      seen["headers"] = kwargs["headers"]
      return httpx.Request(method, url, content=kwargs.get("content"), headers=kwargs["headers"])

    def send(self, request, *, stream):
      return httpx.Response(201, request=request, content=b"{}")

    def close(self):
      return None

  broker.client.close()
  broker.client = FakeClient()
  broker.state = {
    "issuer": "https://www.mobius.you",
    "subject": "user_example",
    "key_generation": 1,
  }
  def capability(**kwargs):
    seen["capability"] = kwargs
    return "token"

  monkeypatch.setattr(broker, "_capability", capability)
  key = "contribution:0123456789abcdef"
  response = broker.proxy(
    method="POST",
    path="/v1/contributions",
    body=b'{"repo":"mobius-os/mobius"}',
    headers={"idempotency-key": key, "x-mobius-request-id": "request:12345678"},
    allow_contributions=True,
  )
  response.close()

  assert seen["url"] == broker_module.CONTRIBUTION_BASE_URL + "/v1/contributions"
  assert seen["headers"]["Idempotency-Key"] == key
  assert seen["capability"]["idempotency_key"] == key
  assert seen["capability"]["audience"] == "mobius-contribution-relay"
  assert seen["capability"]["scope"] == "contribution:submit"


def test_community_proxy_binds_canonical_query_and_rejects_route_expansion(
  broker, monkeypatch,
):
  seen = {}

  class FakeClient:
    def build_request(self, method, url, **kwargs):
      seen["url"] = url
      return httpx.Request(method, url, headers=kwargs["headers"])

    def send(self, request, *, stream):
      return httpx.Response(200, request=request, content=b"{}")

    def close(self):
      return None

  broker.client.close()
  broker.client = FakeClient()
  broker.state = {
    "issuer": "https://www.mobius.you",
    "subject": "user_example",
    "key_generation": 1,
  }
  def capability(**kwargs):
    seen["capability"] = kwargs
    return "token"

  monkeypatch.setattr(broker, "_capability", capability)
  target = "/v1/community/apps?limit=25&offset=0&q=latex&review_status=unreviewed"
  response = broker.proxy(
    method="GET", path=target, body=b"", headers={}, allow_contributions=True,
  )
  response.close()

  assert seen["url"] == broker_module.COMMUNITY_BASE_URL + target
  assert seen["capability"]["path"] == target
  assert seen["capability"]["audience"] == "mobius-community-registry"
  assert seen["capability"]["scope"] == "community:read"

  for forbidden in (
    "/v1/community/apps?offset=0&limit=25",
    "/v1/community/apps?admin=true",
    "/v1/community/apps/app_12345678?limit=2",
    "/v1/community/private-audit",
  ):
    with pytest.raises(FileNotFoundError):
      broker.proxy(
        method="GET", path=forbidden, body=b"", headers={},
        allow_contributions=True,
      )

  for method, forbidden in (
    ("GET", "/v1/models?admin=true"),
    ("POST", "/v1/responses?stream=false"),
    ("POST", "/v1/contributions?repo=other"),
    ("GET", "/v1/contributions/contrib_12345678?subject=user_other"),
  ):
    with pytest.raises(FileNotFoundError):
      broker.proxy(
        method=method, path=forbidden, body=b"", headers={},
        allow_contributions=True,
      )


def test_broker_requires_valid_idempotency_for_all_central_mutations(
  broker, monkeypatch,
):
  broker.state = {
    "issuer": "https://www.mobius.you",
    "subject": "user_example",
    "key_generation": 1,
  }
  monkeypatch.setattr(broker, "_capability", lambda **_kwargs: "token")
  for path in ("/v1/contributions", "/v1/community/publications"):
    with pytest.raises(ValueError, match="idempotency key is required"):
      broker.proxy(
        method="POST", path=path, body=b"{}", headers={},
        allow_contributions=True,
      )


def test_large_body_exception_is_only_for_exact_uds_community_publication():
  assert broker_module._request_body_limit(
    is_unix=True, method="POST", path="/v1/contributions",
  ) == broker_module.MAX_CONTRIBUTION_BODY
  assert broker_module._request_body_limit(
    is_unix=True, method="POST", path="/v1/community/publications",
  ) == broker_module.MAX_COMMUNITY_PUBLICATION_BODY
  for args in (
    (False, "POST", "/v1/community/publications"),
    (True, "POST", "/v1/community/publications?x=1"),
    (True, "POST", "/v1/contributions?x=1"),
    (True, "POST", "/v1/responses"),
    (True, "GET", "/v1/community/publications"),
  ):
    assert broker_module._request_body_limit(
      is_unix=args[0], method=args[1], path=args[2],
    ) == broker_module.MAX_BODY


def test_handler_supports_every_allowlisted_community_http_method():
  handler = broker_module._Handler
  assert handler.do_GET is handler._handle
  assert handler.do_POST is handler._handle
  assert handler.do_PUT is handler._handle
  assert handler.do_DELETE is handler._handle


def test_unix_handler_rejects_identity_queries_and_forwards_put_delete():
  # AF_UNIX paths are capped at roughly 108 bytes on Linux; contribution
  # worktrees can make pytest's ordinary tmp_path longer than that.
  socket_dir = tempfile.TemporaryDirectory(prefix="mobius-broker-")
  socket_path = Path(socket_dir.name) / "broker.sock"
  seen = []

  class FakeBroker:
    def identity(self):
      return {"linked": True}

    def proxy(self, *, method, path, body, headers, allow_contributions):
      seen.append((method, path, body, allow_contributions))
      request = httpx.Request(method, "https://central.test" + path)
      payload = json.dumps({"method": method}).encode()
      return httpx.Response(
        200,
        request=request,
        headers={"Content-Type": "application/json"},
        stream=httpx.ByteStream(payload),
      )

  server = broker_module._UnixServer(str(socket_path), broker_module._Handler)
  server.broker = FakeBroker()
  server.is_unix = True
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  try:
    transport = httpx.HTTPTransport(uds=str(socket_path))
    with httpx.Client(transport=transport, base_url="http://broker") as client:
      assert client.get("/identity").json() == {"linked": True}
      assert client.get("/identity?subject=user_other").status_code == 404
      put = client.put(
        "/v1/community/apps/app_12345678/rating",
        content=b'{"value":4}',
        headers={"Idempotency-Key": "rating:1234567890abcdef"},
      )
      delete = client.delete(
        "/v1/community/comments/comment_12345678",
        headers={"Idempotency-Key": "comment:1234567890abcdef"},
      )
    assert put.json() == {"method": "PUT"}
    assert delete.json() == {"method": "DELETE"}
    assert seen == [
      ("PUT", "/v1/community/apps/app_12345678/rating", b'{"value":4}', True),
      ("DELETE", "/v1/community/comments/comment_12345678", b"", True),
    ]
  finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    socket_dir.cleanup()
