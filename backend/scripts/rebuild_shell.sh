#!/bin/sh
set -e

NOTIFY_URL="${API_BASE_URL:-http://localhost:8000}/api/notify"
AUTH="Authorization: Bearer ${AGENT_TOKEN}"
CT="Content-Type: application/json"

# best-effort notification — curl failure should not abort rebuild
notify() {
  curl -s -X POST "$NOTIFY_URL" -H "$AUTH" -H "$CT" -d "$1" >/dev/null 2>&1 || true
}

notify '{"type":"shell_rebuilding"}'

cd /data/shell
if npx vite build 2>&1; then
  echo "Shell rebuilt successfully."
  notify '{"type":"shell_rebuilt"}'
else
  err="vite build failed"
  echo "$err" >&2
  notify "{\"type\":\"shell_rebuild_failed\",\"error\":\"$err\"}"
  exit 1
fi
