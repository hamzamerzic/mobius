#!/usr/bin/env bash
# Proves the root recovery target cannot reveal its bearer or sniff worker HTTP.

set -euo pipefail

IMAGE=${MOBIUS_IMAGE:-mobius}
CONTAINER="mobius-recovery-target-security-$$"
ENV_FILE=$(mktemp /tmp/mobius-recovery-target-security.XXXXXX)
TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    docker logs "$CONTAINER" 2>/dev/null || true
  fi
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -f "$ENV_FILE"
  exit "$status"
}
trap cleanup EXIT INT TERM

chmod 600 "$ENV_FILE"
printf '%s\n' \
  'MOBIUS_BOOT_MODE=recovery' \
  'MOBIUS_RECOVERY_TARGET_PORT=18002' \
  'DATA_DIR=/data' \
  'BUILD_SHA=runtime-spoof-must-not-win' \
  "MOBIUS_RECOVERY_TARGET_TOKEN=$TOKEN" >"$ENV_FILE"

# Add both dangerous capabilities deliberately. targetd must remove them itself
# so this proves the invariant independently of Compose or platform defaults.
docker run -d \
  --name "$CONTAINER" \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /run \
  --tmpfs /data \
  --cap-add NET_ADMIN \
  --cap-add NET_RAW \
  --no-healthcheck \
  --env-file "$ENV_FILE" \
  -p 127.0.0.1::18002 \
  "$IMAGE" >/dev/null
rm -f "$ENV_FILE"

BINDING=$(docker port "$CONTAINER" 18002/tcp)
PORT=${BINDING##*:}
MOBIUS_TEST_URL="http://127.0.0.1:$PORT" \
MOBIUS_TEST_TOKEN="$TOKEN" \
python3 - <<'PY'
import base64
import errno
import json
import os
import time
import urllib.error
import urllib.request

url = os.environ["MOBIUS_TEST_URL"]
token = os.environ["MOBIUS_TEST_TOKEN"]
headers = {
  "Authorization": f"Bearer {token}",
  "Content-Type": "application/json",
}


def request(path, payload=None):
  body = None if payload is None else json.dumps(payload).encode()
  method = "GET" if body is None else "POST"
  req = urllib.request.Request(
    url + path, data=body, headers=headers, method=method,
  )
  with urllib.request.urlopen(req, timeout=5) as response:
    return json.load(response)


deadline = time.monotonic() + 30
while True:
  try:
    health = request("/v1/health")
    break
  except (OSError, urllib.error.URLError):
    if time.monotonic() >= deadline:
      raise
    time.sleep(0.25)

revision = health["build_sha"]
assert len(revision) == 40 and all(c in "0123456789abcdef" for c in revision)
assert revision != "runtime-spoof-must-not-win"

child_program = r'''
import json
import os
import socket

caps = {}
with open("/proc/self/status", encoding="ascii") as status:
  for line in status:
    name, _, value = line.partition(":")
    if name in {"CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"}:
      caps[name] = value.strip()

try:
  packet_socket = socket.socket(
    socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3),
  )
except OSError as exc:
  packet = {"opened": False, "errno": exc.errno}
else:
  packet = {"opened": True, "errno": None}
  packet_socket.close()

try:
  with open("/proc/1/environ", "rb") as environ:
    parent_environment = environ.read()
except OSError as exc:
  proc = {"readable": False, "errno": exc.errno, "data": ""}
else:
  proc = {
    "readable": True,
    "errno": None,
    "data": parent_environment.decode("latin1"),
  }

print(json.dumps({
  "uid": os.geteuid(),
  "pid_one": open("/proc/1/cmdline", "rb").read().decode("latin1"),
  "caps": caps,
  "packet": packet,
  "proc": proc,
}))
'''
result = request("/v1/exec", {
  "argv": ["/usr/local/bin/python3", "-c", child_program],
  "cwd": "/tmp",
})
assert result["exit_code"] == 0, result
child = json.loads(base64.b64decode(result["stdout_base64"]))
assert child["uid"] == 0
assert "targetd.py" in child["pid_one"]
assert child["packet"]["opened"] is False
assert child["packet"]["errno"] in {errno.EPERM, errno.EACCES}
assert token not in child["proc"]["data"]
assert "MOBIUS_RECOVERY_TARGET_TOKEN=" not in child["proc"]["data"]

blocked_mask = (1 << 12) | (1 << 13)
assert set(child["caps"]) == {"CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"}
for name, raw_value in child["caps"].items():
  assert int(raw_value, 16) & blocked_mask == 0, (name, raw_value)

print(json.dumps({
  "build_sha": revision,
  "packet_errno": child["packet"]["errno"],
  "capabilities": child["caps"],
  "pid_one": child["pid_one"],
}, sort_keys=True))
PY
