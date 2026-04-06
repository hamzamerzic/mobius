#!/bin/sh
# Notify the frontend that theme.css has changed.
# Call this after writing /data/shared/theme.css so the
# user sees the change immediately mid-conversation.

NOTIFY_URL="${API_BASE_URL:-http://localhost:8000}/api/notify"
AUTH="Authorization: Bearer ${AGENT_TOKEN}"
CT="Content-Type: application/json"

curl -s -X POST "$NOTIFY_URL" -H "$AUTH" -H "$CT" \
  -d '{"type":"theme_updated"}' >/dev/null 2>&1 || true
