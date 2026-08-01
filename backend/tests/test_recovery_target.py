from __future__ import annotations

import base64
import errno
import importlib.util
import json
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest


_TARGET_PATH = (
  Path(__file__).resolve().parents[1] / "recovery_target" / "targetd.py"
)


@pytest.fixture()
def target(monkeypatch):
  spec = importlib.util.spec_from_file_location("test_recovery_targetd", _TARGET_PATH)
  assert spec and spec.loader
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  monkeypatch.setenv("MOBIUS_RECOVERY_TARGET_TOKEN", "t" * 43)
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


def _request(url, path, *, token="t" * 43, body=None):
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
  with urllib.request.urlopen(request, timeout=5) as response:
    return response.status, json.load(response)


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
    }


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
  assert result["stdout"] == "hello"
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


@pytest.mark.parametrize("value", ["", "short", "x" * 513])
def test_target_token_fails_closed(target, monkeypatch, value):
  monkeypatch.setenv("MOBIUS_RECOVERY_TARGET_TOKEN", value)
  with pytest.raises(RuntimeError, match="32-512"):
    target._token()


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
