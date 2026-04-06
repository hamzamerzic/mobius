# backend/tests/test_uploads.py
import io
from app import models


def test_upload_single_file(client, db, auth, chat):
  """POST /api/chats/{id}/uploads stores file and returns record."""
  data = io.BytesIO(b"hello world")
  res = client.post(
    f"/api/chats/{chat.id}/uploads",
    files=[("files", ("hello.txt", data, "text/plain"))],
    headers=auth,
  )
  assert res.status_code == 200
  records = res.json()
  assert len(records) == 1
  assert records[0]["name"] == "hello.txt"
  assert records[0]["size"] == 11
  assert records[0]["mime_type"] == "text/plain"

  db.refresh(chat)
  assert len(chat.uploads) == 1
  assert chat.uploads[0]["name"] == "hello.txt"


def test_upload_deduplicates_filename(client, db, auth, chat):
  """Second upload with same name gets a numeric suffix."""
  for _ in range(2):
    client.post(
      f"/api/chats/{chat.id}/uploads",
      files=[("files", ("photo.png", io.BytesIO(b"data"), "image/png"))],
      headers=auth,
    )
  db.refresh(chat)
  names = [u["name"] for u in chat.uploads]
  assert "photo.png" in names
  assert "photo_1.png" in names


def test_list_uploads(client, db, auth, chat):
  """GET /api/chats/{id}/uploads returns the stored upload list."""
  client.post(
    f"/api/chats/{chat.id}/uploads",
    files=[("files", ("a.txt", io.BytesIO(b"x"), "text/plain"))],
    headers=auth,
  )
  res = client.get(f"/api/chats/{chat.id}/uploads", headers=auth)
  assert res.status_code == 200
  assert len(res.json()) == 1


def test_serve_uploaded_file(client, db, auth, chat):
  """GET /api/chats/{id}/uploads/{filename} returns the file content."""
  client.post(
    f"/api/chats/{chat.id}/uploads",
    files=[("files", ("note.txt", io.BytesIO(b"secret"), "text/plain"))],
    headers=auth,
  )
  from app.auth import create_access_token
  token = create_access_token({"sub": "test"})
  res = client.get(
    f"/api/chats/{chat.id}/uploads/note.txt",
    params={"token": token},
  )
  assert res.status_code == 200
  assert res.content == b"secret"


def test_upload_rejects_missing_chat(client, auth):
  """Upload to nonexistent chat must return 404."""
  res = client.post(
    "/api/chats/nope/uploads",
    files=[("files", ("x.txt", io.BytesIO(b"x"), "text/plain"))],
    headers=auth,
  )
  assert res.status_code == 404
