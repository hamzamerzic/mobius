#!/usr/bin/env python3
"""Immutable root repair target used only by an external recovery worker.

This module is deliberately stdlib-only and is launched by the baked entrypoint
before any path below /data is imported.  It is not a recovery user interface or
an agent runner: it is a small, bearer-authenticated capability endpoint for the
separate recovery service.
"""

from __future__ import annotations

import base64
import binascii
import errno
import hmac
import json
import os
import selectors
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


PROTOCOL = "mobius-recovery-target/v1"
DEFAULT_PORT = 18002
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_LIST_ENTRIES = 10_000
MAX_LIST_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_TIMEOUT_SECONDS = 900.0
MAX_ENV_ITEMS = 128
MAX_CONCURRENT_EXEC = 2
_EXEC_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_EXEC)


class RequestError(Exception):
  def __init__(
    self,
    code: str,
    message: str,
    status: HTTPStatus = HTTPStatus.BAD_REQUEST,
  ) -> None:
    super().__init__(message)
    self.code = code
    self.message = message
    self.status = status


def _token() -> str:
  value = os.environ.get("MOBIUS_RECOVERY_TARGET_TOKEN", "")
  if len(value) < 32 or len(value.encode("utf-8")) > 512:
    raise RuntimeError(
      "MOBIUS_RECOVERY_TARGET_TOKEN must contain 32-512 UTF-8 bytes"
    )
  return value


def _absolute_path(value: Any, field: str = "path") -> Path:
  if not isinstance(value, str) or not value or "\x00" in value:
    raise RequestError("invalid_path", f"{field} must be a non-empty path")
  path = Path(value)
  if not path.is_absolute():
    raise RequestError("invalid_path", f"{field} must be absolute")
  return path


def _bounded_int(
  value: Any,
  *,
  field: str,
  default: int,
  minimum: int,
  maximum: int,
) -> int:
  if value is None:
    return default
  if isinstance(value, bool) or not isinstance(value, int):
    raise RequestError("invalid_request", f"{field} must be an integer")
  if value < minimum or value > maximum:
    raise RequestError(
      "invalid_request", f"{field} must be between {minimum} and {maximum}"
    )
  return value


def _decode_base64(value: Any, field: str) -> bytes:
  if not isinstance(value, str):
    raise RequestError("invalid_request", f"{field} must be base64 text")
  try:
    decoded = base64.b64decode(value, validate=True)
  except (binascii.Error, ValueError) as exc:
    raise RequestError("invalid_request", f"{field} is not valid base64") from exc
  if len(decoded) > MAX_FILE_BYTES:
    raise RequestError(
      "payload_too_large",
      f"decoded {field} exceeds {MAX_FILE_BYTES} bytes",
      HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    )
  return decoded


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
  if process.poll() is not None:
    return
  try:
    os.killpg(process.pid, signal.SIGKILL)
  except ProcessLookupError:
    pass


def _run_exec(body: dict[str, Any]) -> dict[str, Any]:
  argv = body.get("argv")
  if (
    not isinstance(argv, list)
    or not argv
    or len(argv) > 256
    or any(not isinstance(item, str) or not item or "\x00" in item for item in argv)
  ):
    raise RequestError(
      "invalid_request", "argv must be a non-empty list of non-empty strings"
    )
  cwd_value = body.get("cwd", "/data")
  cwd = _absolute_path(cwd_value, "cwd")
  if not cwd.is_dir():
    raise RequestError("invalid_cwd", "cwd must name an existing directory")

  timeout_raw = body.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
  if isinstance(timeout_raw, bool) or not isinstance(timeout_raw, (int, float)):
    raise RequestError("invalid_request", "timeout_seconds must be a number")
  timeout = float(timeout_raw)
  if not 0.1 <= timeout <= MAX_TIMEOUT_SECONDS:
    raise RequestError(
      "invalid_request",
      f"timeout_seconds must be between 0.1 and {MAX_TIMEOUT_SECONDS:g}",
    )

  requested_env = body.get("env", {})
  if not isinstance(requested_env, dict) or len(requested_env) > MAX_ENV_ITEMS:
    raise RequestError(
      "invalid_request", f"env must contain at most {MAX_ENV_ITEMS} entries"
    )
  env = {
    "HOME": "/root",
    "LANG": os.environ.get("LANG", "C.UTF-8"),
    "PATH": os.environ.get(
      "PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    ),
    "DATA_DIR": os.environ.get("DATA_DIR", "/data"),
  }
  for key, value in requested_env.items():
    if (
      not isinstance(key, str)
      or not key
      or "=" in key
      or "\x00" in key
      or not isinstance(value, str)
      or "\x00" in value
    ):
      raise RequestError("invalid_request", "env keys and values must be strings")
    if len(key) > 256 or len(value.encode("utf-8")) > 64 * 1024:
      raise RequestError("invalid_request", "env key or value is too large")
    env[key] = value

  if "stdin" in body and "stdin_base64" in body:
    raise RequestError(
      "invalid_request", "stdin and stdin_base64 are mutually exclusive"
    )
  if "stdin_base64" in body:
    stdin = _decode_base64(body["stdin_base64"], "stdin_base64")
  else:
    stdin_value = body.get("stdin", "")
    if not isinstance(stdin_value, str):
      raise RequestError("invalid_request", "stdin must be a string")
    stdin = stdin_value.encode("utf-8")
    if len(stdin) > MAX_FILE_BYTES:
      raise RequestError(
        "payload_too_large",
        f"stdin exceeds {MAX_FILE_BYTES} bytes",
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
      )

  if not _EXEC_SLOTS.acquire(blocking=False):
    raise RequestError(
      "exec_busy",
      "the recovery target is already running the maximum number of commands",
      HTTPStatus.SERVICE_UNAVAILABLE,
    )
  started = time.monotonic()
  process: subprocess.Popen[bytes] | None = None
  try:
    try:
      process = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
      )
    except OSError as exc:
      raise RequestError(
        "exec_failed", str(exc), HTTPStatus.UNPROCESSABLE_ENTITY
      ) from exc
    assert process.stdin and process.stdout and process.stderr
    for stream in (process.stdin, process.stdout, process.stderr):
      os.set_blocking(stream.fileno(), False)

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdin_view = memoryview(stdin)
    stdin_offset = 0
    if stdin:
      selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
    else:
      process.stdin.close()

    output = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = False
    timed_out = False
    while selector.get_map():
      remaining = timeout - (time.monotonic() - started)
      if remaining <= 0:
        timed_out = True
        _kill_process_group(process)
        remaining = 0.1
      events = selector.select(min(max(remaining, 0.01), 0.25))
      for key, _mask in events:
        stream = key.fileobj
        kind = key.data
        if kind == "stdin":
          try:
            written = os.write(stream.fileno(), stdin_view[stdin_offset:])
            stdin_offset += written
          except BrokenPipeError:
            stdin_offset = len(stdin_view)
          if stdin_offset >= len(stdin_view):
            selector.unregister(stream)
            stream.close()
          continue
        try:
          chunk = os.read(stream.fileno(), 64 * 1024)
        except BlockingIOError:
          continue
        if not chunk:
          selector.unregister(stream)
          stream.close()
          continue
        target = output[kind]
        room = MAX_OUTPUT_BYTES - len(target)
        if room > 0:
          target.extend(chunk[:room])
        if len(chunk) > room:
          truncated = True
          _kill_process_group(process)

      if process.poll() is not None:
        # Pipes may still contain a final kernel-buffered chunk. Keep draining
        # them, but an unwritten stdin pipe can now be retired.
        if process.stdin in [item.fileobj for item in selector.get_map().values()]:
          selector.unregister(process.stdin)
          process.stdin.close()
    exit_code = process.wait(timeout=2)
    elapsed_ms = round((time.monotonic() - started) * 1000)
    return {
      "exit_code": exit_code,
      "stdout_base64": base64.b64encode(output["stdout"]).decode("ascii"),
      "stderr_base64": base64.b64encode(output["stderr"]).decode("ascii"),
      "truncated": truncated,
      "timed_out": timed_out,
      "duration_ms": elapsed_ms,
    }
  finally:
    if process is not None and process.poll() is None:
      _kill_process_group(process)
      try:
        process.wait(timeout=2)
      except subprocess.TimeoutExpired:
        pass
    _EXEC_SLOTS.release()


def _read_file(body: dict[str, Any]) -> dict[str, Any]:
  path = _absolute_path(body.get("path"))
  offset = _bounded_int(
    body.get("offset"), field="offset", default=0, minimum=0, maximum=2**63 - 1
  )
  limit = _bounded_int(
    body.get("limit"),
    field="limit",
    default=MAX_FILE_BYTES,
    minimum=1,
    maximum=MAX_FILE_BYTES,
  )
  try:
    st = path.stat()
    if not stat.S_ISREG(st.st_mode):
      raise RequestError("not_a_file", "path is not a regular file")
    with path.open("rb") as handle:
      handle.seek(offset)
      data = handle.read(limit)
    return {
      "path": str(path),
      "offset": offset,
      "data_base64": base64.b64encode(data).decode("ascii"),
      "eof": offset + len(data) >= st.st_size,
      "size": st.st_size,
      "mode": stat.S_IMODE(st.st_mode),
      "uid": st.st_uid,
      "gid": st.st_gid,
    }
  except RequestError:
    raise
  except OSError as exc:
    raise RequestError(
      "fs_read_failed", str(exc), HTTPStatus.UNPROCESSABLE_ENTITY
    ) from exc


def _write_file(body: dict[str, Any]) -> dict[str, Any]:
  path = _absolute_path(body.get("path"))
  data = _decode_base64(body.get("data_base64"), "data_base64")
  mode = _bounded_int(
    body.get("mode"), field="mode", default=0o600, minimum=0, maximum=0o7777
  )
  atomic = body.get("atomic", True)
  if not isinstance(atomic, bool):
    raise RequestError("invalid_request", "atomic must be a boolean")
  if not path.parent.is_dir():
    raise RequestError("missing_parent", "the destination parent does not exist")

  temp_path: Path | None = None
  try:
    if atomic:
      fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
      temp_path = Path(raw_temp)
      try:
        os.fchmod(fd, mode)
        offset = 0
        while offset < len(data):
          offset += os.write(fd, data[offset:])
        os.fsync(fd)
      finally:
        os.close(fd)
      os.replace(temp_path, path)
      temp_path = None
    else:
      flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
      flags |= getattr(os, "O_NOFOLLOW", 0)
      fd = os.open(path, flags, mode)
      try:
        os.fchmod(fd, mode)
        offset = 0
        while offset < len(data):
          offset += os.write(fd, data[offset:])
        os.fsync(fd)
      finally:
        os.close(fd)
    return {"path": str(path), "bytes_written": len(data), "mode": mode}
  except OSError as exc:
    raise RequestError(
      "fs_write_failed", str(exc), HTTPStatus.UNPROCESSABLE_ENTITY
    ) from exc
  finally:
    if temp_path is not None:
      temp_path.unlink(missing_ok=True)


def _list_directory(body: dict[str, Any]) -> dict[str, Any]:
  path = _absolute_path(body.get("path"))
  try:
    entries: list[dict[str, Any]] = []
    encoded_bytes = len(str(path).encode("utf-8")) + 64
    with os.scandir(path) as iterator:
      for entry in iterator:
        if len(entries) >= MAX_LIST_ENTRIES:
          raise RequestError(
            "too_many_entries",
            f"directory contains more than {MAX_LIST_ENTRIES} entries",
            HTTPStatus.UNPROCESSABLE_ENTITY,
          )
        info = entry.stat(follow_symlinks=False)
        kind = (
          "symlink" if stat.S_ISLNK(info.st_mode)
          else "directory" if stat.S_ISDIR(info.st_mode)
          else "file" if stat.S_ISREG(info.st_mode)
          else "other"
        )
        item: dict[str, Any] = {
          "name": entry.name,
          "type": kind,
          "size": info.st_size,
          "mode": stat.S_IMODE(info.st_mode),
          "uid": info.st_uid,
          "gid": info.st_gid,
          "mtime_ns": info.st_mtime_ns,
        }
        if kind == "symlink":
          item["target"] = os.readlink(entry.path)
        encoded_bytes += len(
          json.dumps(item, separators=(",", ":")).encode("utf-8")
        ) + 1
        if encoded_bytes > MAX_LIST_RESPONSE_BYTES:
          raise RequestError(
            "response_too_large",
            f"directory metadata exceeds {MAX_LIST_RESPONSE_BYTES} bytes",
            HTTPStatus.UNPROCESSABLE_ENTITY,
          )
        entries.append(item)
    entries.sort(key=lambda item: item["name"])
    return {"path": str(path), "entries": entries}
  except RequestError:
    raise
  except OSError as exc:
    raise RequestError(
      "fs_list_failed", str(exc), HTTPStatus.UNPROCESSABLE_ENTITY
    ) from exc


class _Handler(BaseHTTPRequestHandler):
  protocol_version = "HTTP/1.1"
  server_version = "MobiusRecoveryTarget/1"

  def log_message(self, fmt: str, *args: object) -> None:
    print(f"recovery-target: {self.address_string()} {fmt % args}", flush=True)

  def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    self.send_response(status.value)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(raw)))
    self.send_header("Cache-Control", "no-store")
    self.send_header("X-Content-Type-Options", "nosniff")
    self.send_header("Connection", "close")
    self.end_headers()
    self.wfile.write(raw)
    self.close_connection = True

  def _error(self, error: RequestError) -> None:
    self._send(
      error.status,
      {"error": {"code": error.code, "message": error.message}},
    )

  def _authorized(self) -> bool:
    expected = f"Bearer {_token()}"
    supplied = self.headers.get("Authorization", "")
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
      self._send(
        HTTPStatus.UNAUTHORIZED,
        {"error": {"code": "unauthorized", "message": "invalid bearer token"}},
      )
      return False
    return True

  def _body(self) -> dict[str, Any]:
    if self.headers.get("Transfer-Encoding"):
      raise RequestError(
        "invalid_framing", "Transfer-Encoding is not supported"
      )
    raw_length = self.headers.get("Content-Length")
    if raw_length is None or not raw_length.isdecimal():
      raise RequestError("invalid_framing", "a valid Content-Length is required")
    length = int(raw_length)
    if length > MAX_REQUEST_BYTES:
      raise RequestError(
        "payload_too_large",
        f"request exceeds {MAX_REQUEST_BYTES} bytes",
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
      )
    raw = self.rfile.read(length)
    if len(raw) != length:
      raise RequestError("invalid_framing", "request body ended early")
    try:
      value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
      raise RequestError("invalid_json", "request body must be a JSON object") from exc
    if not isinstance(value, dict):
      raise RequestError("invalid_json", "request body must be a JSON object")
    return value

  def do_GET(self) -> None:  # noqa: N802
    if not self._authorized():
      return
    if self.path != "/v1/health":
      self._error(RequestError("not_found", "endpoint not found", HTTPStatus.NOT_FOUND))
      return
    self._send(HTTPStatus.OK, {
      "protocol": PROTOCOL,
      "target": "mobius",
      "mode": "recovery",
      "build_sha": os.environ.get("BUILD_SHA", "unknown"),
    })

  def do_POST(self) -> None:  # noqa: N802
    if not self._authorized():
      return
    handlers = {
      "/v1/exec": _run_exec,
      "/v1/fs/read": _read_file,
      "/v1/fs/write": _write_file,
      "/v1/fs/list": _list_directory,
    }
    operation = handlers.get(self.path)
    if operation is None:
      self._error(RequestError("not_found", "endpoint not found", HTTPStatus.NOT_FOUND))
      return
    try:
      result = operation(self._body())
    except RequestError as exc:
      self._error(exc)
      return
    except Exception:
      self._error(RequestError(
        "internal_error", "recovery target operation failed", HTTPStatus.INTERNAL_SERVER_ERROR
      ))
      return
    self._send(HTTPStatus.OK, result)


class _DualStackServer(ThreadingHTTPServer):
  address_family = socket.AF_INET6
  daemon_threads = True
  allow_reuse_address = True

  def server_bind(self) -> None:
    self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    super().server_bind()


class _IPv4Server(ThreadingHTTPServer):
  daemon_threads = True
  allow_reuse_address = True


def _create_server(port: int) -> ThreadingHTTPServer:
  """Prefer one dual-stack socket, but keep recovery usable without IPv6."""
  try:
    return _DualStackServer(("::", port), _Handler)
  except OSError as exc:
    if exc.errno not in {
      errno.EAFNOSUPPORT,
      errno.EADDRNOTAVAIL,
      errno.ENOPROTOOPT,
      errno.EPROTONOSUPPORT,
    }:
      raise
    print(
      f"recovery-target: IPv6 unavailable ({exc}); falling back to IPv4",
      flush=True,
    )
    return _IPv4Server(("0.0.0.0", port), _Handler)


def main() -> None:
  if os.environ.get("MOBIUS_BOOT_MODE") != "recovery":
    raise SystemExit("recovery target refuses to run outside recovery boot mode")
  if os.geteuid() != 0:
    raise SystemExit("recovery target must run as root")
  token = _token()
  del token
  raw_port = os.environ.get("MOBIUS_RECOVERY_TARGET_PORT", str(DEFAULT_PORT))
  try:
    port = int(raw_port)
  except ValueError as exc:
    raise SystemExit("MOBIUS_RECOVERY_TARGET_PORT must be an integer") from exc
  if not 1 <= port <= 65535:
    raise SystemExit("MOBIUS_RECOVERY_TARGET_PORT must be between 1 and 65535")
  # Every endpoint, including health, requires the bearer token. Managed
  # launchers therefore clear provider-level unauthenticated health checks and
  # probe /v1/health themselves before handing the worker to the owner.
  server = _create_server(port)
  print(
    f"Mobius recovery target {PROTOCOL} listening privately on [::]:{port}",
    flush=True,
  )
  server.serve_forever(poll_interval=0.25)


if __name__ == "__main__":
  main()
