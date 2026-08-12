"""First-class Project persistence, confinement, and legacy compatibility."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest

from app import models
from app.chat_context import _build_app_context
from app.chat_retention import purge_expired_chat_tombstones
from app.project_retention import purge_expired_project_tombstones
from app.timeutil import SOFT_DELETE_TTL, now_naive_utc


def _create_project_chat(client, auth, project, title="New chat", request_id=None):
  response = client.post(
    f"/api/projects/{project['id']}/chats",
    headers=auth,
    json={
      "title": title,
      "recovery_request_id": request_id or f"{project['id']}:{title}",
    },
  )
  assert response.status_code == 201, response.text
  return response.json()


def test_blank_project_starts_without_chat_and_has_confined_files(
  client, auth, db,
):
  created = client.post(
    "/api/projects",
    headers=auth,
    json={"name": "Research", "template_id": "blank"},
  )
  assert created.status_code == 200, created.text
  project = created.json()
  assert project["name"] == "Research"
  assert project["chat_id"] is None
  assert client.get(
    f"/api/projects/{project['id']}/chats", headers=auth,
  ).json() == []

  first_chat = _create_project_chat(
    client, auth, project, "Research notes", "notes-chat",
  )
  second_chat = _create_project_chat(
    client, auth, project, "Implementation", "implementation-chat",
  )
  listed_chats = client.get(
    f"/api/projects/{project['id']}/chats", headers=auth,
  ).json()
  assert {row["id"] for row in listed_chats} == {
    first_chat["id"], second_chat["id"],
  }
  assert all(db.get(models.Chat, row["id"]).project_id == project["id"]
             for row in listed_chats)
  # Project chats remain directly addressable, but live inside their Project
  # rather than appearing as unrelated global Recents.
  chat_list = client.get("/api/chats", headers=auth)
  assert chat_list.status_code == 200
  assert not ({first_chat["id"], second_chat["id"]}
              & {row["id"] for row in chat_list.json()})

  saved = client.put(
    f"/api/projects/{project['id']}/file?path=notes/idea.md",
    headers=auth,
    json={"content": "A durable idea."},
  )
  assert saved.status_code == 200, saved.text
  listing = client.get(
    f"/api/projects/{project['id']}/files?path=notes", headers=auth,
  )
  assert listing.status_code == 200
  assert listing.json()["entries"][0]["path"] == "notes/idea.md"
  opened = client.get(
    f"/api/projects/{project['id']}/file?path=notes/idea.md", headers=auth,
  )
  assert opened.json()["content"] == "A durable idea."

  traversal = client.get(
    f"/api/projects/{project['id']}/file?path=../../etc/passwd", headers=auth,
  )
  assert traversal.status_code in (400, 404)

  folder = client.post(
    f"/api/projects/{project['id']}/folder",
    headers=auth,
    json={"path": "assets/images"},
  )
  assert folder.status_code == 200, folder.text
  assert folder.json()["path"] == "assets/images"
  root_listing = client.get(
    f"/api/projects/{project['id']}/files", headers=auth,
  ).json()
  assert any(row["path"] == "assets" and row["type"] == "directory"
             for row in root_listing["entries"])


def test_nested_symlink_parent_cannot_escape_project_root(client, auth, db):
  project = client.post(
    "/api/projects", headers=auth,
    json={"name": "Confined", "template_id": "blank"},
  ).json()
  row = db.get(models.Project, project["id"])
  root = Path(os.environ["DATA_DIR"]) / row.root_path
  outside = Path(os.environ["DATA_DIR"]) / "outside-project"
  outside.mkdir()
  (outside / "secret.txt").write_text("secret")
  (root / "nested").symlink_to(outside, target_is_directory=True)

  for method, endpoint, kwargs in (
    (client.get, "file?path=nested/secret.txt", {}),
    (client.put, "file?path=nested/new.txt", {"json": {"content": "escape"}}),
    (client.delete, "file?path=nested/secret.txt", {}),
  ):
    response = method(
      f"/api/projects/{project['id']}/{endpoint}", headers=auth, **kwargs,
    )
    assert response.status_code in (400, 403), response.text
  assert (outside / "secret.txt").read_text() == "secret"
  assert not (outside / "new.txt").exists()


def test_project_creation_retry_is_idempotent(client, auth, db):
  body = {
    "name": "Retry-safe",
    "template_id": "blank",
    "recovery_request_id": "browser-request-1",
  }
  first = client.post("/api/projects", headers=auth, json=body)
  second = client.post("/api/projects", headers=auth, json=body)
  assert first.status_code == second.status_code == 200
  assert first.json()["id"] == second.json()["id"]
  assert first.json()["chat_id"] == second.json()["chat_id"]
  assert db.query(models.Project).count() == 1
  assert db.query(models.Chat).count() == 0


def test_concurrent_project_creation_retry_has_one_row_and_root(client, auth, db):
  body = {
    "name": "Concurrent",
    "template_id": "blank",
    "recovery_request_id": "same-concurrent-request",
  }
  with ThreadPoolExecutor(max_workers=2) as pool:
    responses = list(pool.map(
      lambda _: client.post("/api/projects", headers=auth, json=body),
      range(2),
    ))
  assert [response.status_code for response in responses] == [200, 200]
  assert len({response.json()["id"] for response in responses}) == 1
  assert db.query(models.Project).count() == 1
  assert db.query(models.Chat).count() == 0
  row = db.query(models.Project).one()
  assert (Path(os.environ["DATA_DIR"]) / row.root_path).is_dir()


def test_each_project_chat_gets_context_and_can_be_deleted_independently(
  client, auth, db,
):
  project = client.post(
    "/api/projects", headers=auth,
    json={"name": "Site", "template_id": "blank"},
  ).json()
  chat = _create_project_chat(client, auth, project, "Site plan")

  block, env = _build_app_context(db, chat["id"], os.environ["DATA_DIR"])
  assert "<project_context>" in block
  assert env["PROJECT_ID"] == project["id"]
  assert Path(env["PROJECT_ROOT"]).is_dir()
  deleted = client.delete(f"/api/chats/{chat['id']}", headers=auth)
  assert deleted.status_code == 204
  assert client.get(
    f"/api/projects/{project['id']}/chats", headers=auth,
  ).json() == []


def test_manifest_template_scaffolds_files_and_snapshots_metadata(
  client, auth, db,
):
  source = Path(os.environ["DATA_DIR"]) / "apps" / "latex"
  (source / "templates").mkdir(parents=True)
  (source / "templates" / "main.tex").write_text("\\documentclass{article}")
  app = models.App(
    name="LaTeX", description="Documents", jsx_source="",
    slug="latex", source_dir=str(source), version="3.0.0",
    project_templates_json=[{
      "id": "latex",
      "name": "LaTeX document",
      "description": "Typeset a document.",
      "guidance": "Use tectonic for builds.",
      "skills": ["latex"],
      "dependencies": ["tectonic"],
      "previews": [{
        "id": "pdf", "name": "PDF", "kind": "pdf", "path": "main.pdf",
      }],
      "actions": [{
        "id": "build", "name": "Build PDF", "prompt": "Compile main.tex.",
      }],
      "files": {"main.tex": "templates/main.tex"},
    }],
  )
  db.add(app)
  db.commit()

  templates = client.get("/api/projects/templates", headers=auth).json()
  assert [row["key"] for row in templates] == ["blank", "latex:latex"]
  created = client.post(
    "/api/projects", headers=auth,
    json={"name": "Paper", "template_id": "latex:latex"},
  )
  assert created.status_code == 200, created.text
  project = created.json()
  assert project["source_app_id"] == app.id
  assert project["template"]["dependencies"] == ["tectonic"]
  assert project["template"]["previews"][0]["path"] == "main.pdf"
  assert project["template"]["actions"][0]["prompt"] == "Compile main.tex."
  opened = client.get(
    f"/api/projects/{project['id']}/file?path=main.tex", headers=auth,
  )
  assert opened.status_code == 200, opened.text
  assert opened.json()["content"] == "\\documentclass{article}"

  binary = client.put(
    f"/api/projects/{project['id']}/file-bytes?path=figure.png",
    headers={**auth, "Content-Type": "application/octet-stream"},
    content=b"\x89PNG\r\n\x1a\n",
  )
  assert binary.status_code == 200
  downloaded = client.get(
    f"/api/projects/{project['id']}/file?path=figure.png&download=true",
    headers=auth,
  )
  assert downloaded.content == b"\x89PNG\r\n\x1a\n"

  # A later app update cannot reinterpret an existing project.
  app.project_templates_json[0]["dependencies"] = ["different"]
  db.add(app)
  db.commit()
  stable = client.get(f"/api/projects/{project['id']}", headers=auth).json()
  assert stable["template"]["dependencies"] == ["tectonic"]


def test_file_bytes_rejects_malformed_content_length(client, auth):
  project = client.post(
    "/api/projects", headers=auth,
    json={"name": "Headers", "template_id": "blank"},
  ).json()
  malformed = client.put(
    f"/api/projects/{project['id']}/file-bytes?path=asset.bin",
    headers={
      **auth,
      "Content-Type": "application/octet-stream",
      "Content-Length": "not-a-number",
    },
    content=b"asset",
  )
  assert malformed.status_code == 400, malformed.text
  assert "Content-Length" in malformed.json()["detail"]


def test_concurrent_file_writes_and_delete_are_atomic(client, auth):
  project = client.post(
    "/api/projects", headers=auth,
    json={"name": "File races", "template_id": "blank"},
  ).json()
  project_id = project["id"]
  path = "shared/state.txt"
  payloads = ("A" * 8192, "B" * 8192)

  def write(payload):
    return client.put(
      f"/api/projects/{project_id}/file?path={path}",
      headers=auth, json={"content": payload},
    )

  def delete():
    return client.delete(
      f"/api/projects/{project_id}/file?path={path}", headers=auth,
    )

  # Seed once so a concurrent delete has a valid target; unique temp names plus
  # os.replace guarantee the surviving file is one complete writer payload.
  assert write("seed").status_code == 200
  with ThreadPoolExecutor(max_workers=3) as pool:
    responses = [
      pool.submit(write, payloads[0]),
      pool.submit(delete),
      pool.submit(write, payloads[1]),
    ]
    statuses = [future.result().status_code for future in responses]
  assert all(status in (200, 404) for status in statuses), statuses
  final = client.get(
    f"/api/projects/{project_id}/file?path={path}", headers=auth,
  )
  if final.status_code == 200:
    assert final.json()["content"] in payloads
  else:
    assert final.status_code == 404


def test_legacy_import_reuses_project_chat_without_moving_files(
  client, auth, db,
):
  storage = Path(os.environ["DATA_DIR"]) / "apps"
  app_source = storage / "webstudio-source"
  app_source.mkdir(parents=True)
  app = models.App(
    name="Web Studio", description="Sites", jsx_source="",
    slug="webstudio", source_dir=str(app_source),
    project_templates_json=[{
      "id": "web-app", "name": "Web app", "files": {},
      "skills": ["web"], "dependencies": [],
    }],
  )
  db.add(app)
  db.commit()
  db.refresh(app)
  legacy = storage / str(app.id) / "projects" / "portfolio"
  (legacy / "files").mkdir(parents=True)
  (legacy / "files" / "index.html").write_text("<h1>Mine</h1>")
  chat = models.Chat(id="legacy-project-chat", title="Portfolio", messages=[])
  db.add(chat)
  db.commit()
  (legacy / "chat_id.json").write_text(json.dumps({"id": chat.id}))
  (storage / str(app.id) / "projects.json").write_text(json.dumps([
    {"id": "portfolio", "name": "Portfolio"},
  ]))

  candidates = client.get("/api/projects/legacy", headers=auth).json()
  assert candidates == [{
    "legacy_project_id": "portfolio",
    "name": "Portfolio",
    "app_id": app.id,
    "app_name": "Web Studio",
    "imported": False,
  }]
  imported = client.post(
    "/api/projects/import-legacy", headers=auth,
    json={"app_id": app.id, "legacy_project_id": "portfolio"},
  )
  assert imported.status_code == 200, imported.text
  project = imported.json()
  assert project["chat_id"] is None
  db.refresh(chat)
  assert chat.project_id == project["id"]
  assert (legacy / "files" / "index.html").is_file()
  opened = client.get(
    f"/api/projects/{project['id']}/file?path=index.html", headers=auth,
  )
  assert opened.json()["content"] == "<h1>Mine</h1>"

  uninstall = client.delete(f"/api/apps/{app.id}", headers=auth)
  assert uninstall.status_code == 409
  assert uninstall.json()["detail"]["code"] == "app_has_imported_project"
  assert (legacy / "files" / "index.html").read_text() == "<h1>Mine</h1>"


def test_project_delete_and_recover_are_atomic_with_its_live_chats(
  client, auth, db,
):
  project = client.post(
    "/api/projects", headers=auth,
    json={"name": "Recover me", "template_id": "blank"},
  ).json()
  first = _create_project_chat(client, auth, project, "Plan")
  second = _create_project_chat(client, auth, project, "Build")
  row = db.get(models.Project, project["id"])
  root = Path(os.environ["DATA_DIR"]) / row.root_path
  deleted = client.delete(f"/api/projects/{project['id']}", headers=auth)
  assert deleted.status_code == 204
  assert root.is_dir()
  db.expire_all()
  assert db.get(models.Project, project["id"]).deleted_at is not None
  assert db.get(models.Chat, first["id"]).deleted_at is not None
  assert db.get(models.Chat, second["id"]).deleted_at is not None

  direct_chat_recovery = client.post(
    f"/api/chats/{first['id']}/recover", headers=auth,
  )
  assert direct_chat_recovery.status_code == 409
  assert direct_chat_recovery.json()["detail"]["code"] == "project_deleted"

  recovered = client.post(
    f"/api/projects/{project['id']}/recover", headers=auth,
  )
  assert recovered.status_code == 200
  db.expire_all()
  assert db.get(models.Project, project["id"]).deleted_at is None
  assert db.get(models.Chat, first["id"]).deleted_at is None
  assert db.get(models.Chat, second["id"]).deleted_at is None


def _expire_project_pair(db, project_id: str, chat_id: str) -> None:
  expired_at = now_naive_utc() - SOFT_DELETE_TTL - timedelta(seconds=1)
  db.get(models.Project, project_id).deleted_at = expired_at
  db.get(models.Chat, chat_id).deleted_at = expired_at
  db.commit()


def test_project_retention_removes_native_root_and_chat_but_preserves_legacy_root(
  client, auth, db,
):
  native = client.post(
    "/api/projects", headers=auth,
    json={"name": "Native", "template_id": "blank"},
  ).json()
  native_row = db.get(models.Project, native["id"])
  native_root = Path(os.environ["DATA_DIR"]) / native_row.root_path
  native_chat = _create_project_chat(client, auth, native, "Native chat")

  legacy_root = Path(os.environ["DATA_DIR"]) / "apps" / "legacy" / "files"
  legacy_root.mkdir(parents=True)
  (legacy_root / "keep.txt").write_text("legacy")
  legacy_chat = models.Chat(id="expired-legacy-chat", title="Legacy", messages=[])
  legacy_project = models.Project(
    id="75e94b57-fe5d-4bd7-a6e0-e74130566f37",
    name="Imported legacy",
    project_type="webstudio:web-app",
    root_path="apps/legacy/files",
    chat_id=None,
    template_snapshot_json={},
    legacy_source_json={"app_id": 1, "project_id": "default"},
  )
  legacy_project_id = legacy_project.id
  legacy_chat_id = legacy_chat.id
  legacy_chat.project_id = legacy_project_id
  db.add_all([legacy_chat, legacy_project])
  db.commit()
  _expire_project_pair(db, native["id"], native_chat["id"])
  _expire_project_pair(db, legacy_project_id, legacy_chat_id)

  purged_chats = purge_expired_chat_tombstones(db)

  assert db.get(models.Project, native["id"]) is None
  assert db.get(models.Project, legacy_project_id) is None
  assert db.get(models.Chat, native_chat["id"]) is None
  assert db.get(models.Chat, legacy_chat_id) is None
  assert native_chat["id"] in purged_chats
  assert legacy_chat_id in purged_chats
  assert not native_root.exists()
  assert (legacy_root / "keep.txt").read_text() == "legacy"


def test_project_retention_does_not_touch_root_when_database_commit_fails(
  client, auth, db, monkeypatch,
):
  project = client.post(
    "/api/projects", headers=auth,
    json={"name": "Still recoverable", "template_id": "blank"},
  ).json()
  row = db.get(models.Project, project["id"])
  root = Path(os.environ["DATA_DIR"]) / row.root_path
  chat = _create_project_chat(client, auth, project, "Still recoverable chat")
  _expire_project_pair(db, project["id"], chat["id"])

  real_commit = db.commit
  monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))
  with pytest.raises(RuntimeError, match="commit failed"):
    purge_expired_project_tombstones(db)
  assert root.is_dir()
  db.rollback()
  monkeypatch.setattr(db, "commit", real_commit)
  db.expire_all()
  assert db.get(models.Project, project["id"]) is not None
  assert db.get(models.Chat, chat["id"]) is not None


def test_project_retention_retries_native_orphan_after_filesystem_failure(
  client, auth, db, monkeypatch,
):
  project = client.post(
    "/api/projects", headers=auth,
    json={"name": "Retry cleanup", "template_id": "blank"},
  ).json()
  row = db.get(models.Project, project["id"])
  root = Path(os.environ["DATA_DIR"]) / row.root_path
  chat = _create_project_chat(client, auth, project, "Retry cleanup chat")
  _expire_project_pair(db, project["id"], chat["id"])

  import app.project_retention as retention
  real_remove = retention._remove_owned_root
  monkeypatch.setattr(
    retention, "_remove_owned_root",
    lambda _root: (_ for _ in ()).throw(OSError("filesystem busy")),
  )
  assert purge_expired_project_tombstones(db) == [project["id"]]
  assert db.get(models.Project, project["id"]) is None
  assert root.is_dir()

  monkeypatch.setattr(retention, "_remove_owned_root", real_remove)
  assert purge_expired_project_tombstones(db) == []
  assert not root.exists()
