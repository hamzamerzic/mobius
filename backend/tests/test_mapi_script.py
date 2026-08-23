"""Contract tests for the authenticated curl convenience wrapper."""

import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mapi"


def _run_mapi(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess:
  bin_dir = tmp_path / "bin"
  bin_dir.mkdir()
  capture = tmp_path / "curl-arguments"
  fake_curl = bin_dir / "curl"
  fake_curl.write_text(
    "#!/usr/bin/env bash\nprintf '%s\\0' \"$@\" > \"$MAPI_CAPTURE\"\n",
    encoding="utf-8",
  )
  fake_curl.chmod(0o755)
  env = {
    **os.environ,
    "AGENT_TOKEN": "owner-token",
    "API_BASE_URL": "https://mobius.example/",
    "MAPI_CAPTURE": str(capture),
    "PATH": f"{bin_dir}:{os.environ['PATH']}",
  }
  result = subprocess.run(
    [str(SCRIPT), *arguments],
    env=env,
    capture_output=True,
    text=True,
    check=False,
  )
  result.curl_arguments = capture.read_bytes().split(b"\0")[:-1]
  return result


def test_mapi_resolves_api_paths_and_adds_json_for_data(tmp_path: Path):
  result = _run_mapi(
    tmp_path,
    "-X", "PATCH", "/api/connect/hosts/h_1", "-d", '{"name":"Desk"}',
  )

  assert result.returncode == 0, result.stderr
  assert result.curl_arguments == [
    b"-sS",
    b"-H", b"Authorization: Bearer owner-token",
    b"-H", b"Content-Type: application/json",
    b"-X", b"PATCH",
    b"https://mobius.example/api/connect/hosts/h_1",
    b"-d", b'{"name":"Desk"}',
  ]


def test_mapi_preserves_an_explicit_content_type(tmp_path: Path):
  result = _run_mapi(
    tmp_path,
    "/api/storage/shared/theme.css",
    "--data-binary", "@theme.css",
    "-H", "Content-Type: text/css",
  )

  assert result.returncode == 0, result.stderr
  assert result.curl_arguments.count(b"Content-Type: text/css") == 1
  assert b"Content-Type: application/json" not in result.curl_arguments
