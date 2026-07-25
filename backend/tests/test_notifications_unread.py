"""Unread tracking for the notifications page (bell badge, seen-on-open)."""

from app import models
from app.auth import create_app_token
from app.broadcast import get_system_broadcast


def _send(client, auth, **overrides):
  payload = {"title": "Ping", "body": "hello", **overrides}
  res = client.post("/api/notifications/send", headers=auth, json=payload)
  assert res.status_code == 200, res.text
  return res.json()["id"]


def _count(client, auth) -> int:
  res = client.get("/api/notifications/unread-count", headers=auth)
  assert res.status_code == 200, res.text
  return res.json()["count"]


def test_seen_on_open_lifecycle(client, auth):
  """Send → unread; read-all → seen (idempotent); new send → unread again."""
  assert _count(client, auth) == 0

  sent_id = _send(client, auth)
  assert _count(client, auth) == 1
  listed = client.get("/api/notifications", headers=auth).json()
  row = next(n for n in listed if n["id"] == sent_id)
  assert row["read_at"] is None

  first = client.post("/api/notifications/read-all", headers=auth)
  assert first.status_code == 200, first.text
  assert first.json() == {"updated": 1}
  assert _count(client, auth) == 0
  listed = client.get("/api/notifications", headers=auth).json()
  row = next(n for n in listed if n["id"] == sent_id)
  assert row["read_at"] is not None

  # Idempotent: a repeat call touches nothing and stamps nothing anew.
  second = client.post("/api/notifications/read-all", headers=auth)
  assert second.status_code == 200
  assert second.json() == {"updated": 0}

  # A notification arriving after read-all counts as unread again.
  _send(client, auth, title="Later")
  assert _count(client, auth) == 1


def test_notification_created_published_on_system_bus(client, auth):
  """Every notify_owner call nudges the bell badge over the system stream."""
  bus = get_system_broadcast()
  events = bus.subscribe()
  try:
    sent_id = _send(client, auth)
    assert events.get_nowait() == {
      "type": "notification_created", "id": sent_id,
    }
  finally:
    bus.unsubscribe(events)


def test_app_attributed_send_publishes_activity_then_badge(client, auth, db):
  """App-sourced sends keep the drawer-dot event AND gain the badge nudge."""
  app = models.App(
    name="News", description="",
    jsx_source="export default function App(){}",
    compiled_path="/tmp/app.js",
  )
  db.add(app)
  db.commit()
  db.refresh(app)

  bus = get_system_broadcast()
  events = bus.subscribe()
  try:
    sent_id = _send(
      client, auth, source_type="app", source_id=str(app.id),
    )
    assert events.get_nowait() == {
      "type": "app_activity", "appId": str(app.id),
    }
    assert events.get_nowait() == {
      "type": "notification_created", "id": sent_id,
    }
  finally:
    bus.unsubscribe(events)


def test_unread_endpoints_are_owner_only(client, auth, db):
  """The bell is the owner's surface: no token → 401, app token → 403."""
  assert client.get("/api/notifications/unread-count").status_code == 401
  assert client.post("/api/notifications/read-all").status_code == 401

  app = models.App(
    name="Probe", description="",
    jsx_source="export default function App(){}",
    compiled_path="/tmp/probe.js",
  )
  db.add(app)
  db.commit()
  db.refresh(app)
  owner = db.query(models.Owner).first()
  app_headers = {
    "Authorization": "Bearer " + create_app_token(
      app.id, owner.username, owner.token_epoch, app.token_nonce,
    ),
  }
  assert client.get(
    "/api/notifications/unread-count", headers=app_headers,
  ).status_code == 403
  assert client.post(
    "/api/notifications/read-all", headers=app_headers,
  ).status_code == 403
