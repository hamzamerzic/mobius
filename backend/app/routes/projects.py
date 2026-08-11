"""First-class owner Projects: persistence, templates, and confined files."""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from app import models, providers, questions
from app.broadcast import get_system_broadcast
from app.chat import (
  _finish_run,
  bump_run_generation,
  is_chat_running,
  mark_chat_deleted,
  recover_chat_generation,
  stop_chat_for,
)
from app.config import get_settings
from app.database import get_db
from app.deps import get_current_owner, reject_cross_site
from app.path_utils import validate_path_within_base
from app.project_retention import PROJECT_LIFECYCLE_LOCK
from app.timeutil import now_naive_utc, SOFT_DELETE_TTL


router = APIRouter(prefix="/api/projects", tags=["projects"])
log = logging.getLogger(__name__)

_READ_MAX = 10 * 1024 * 1024
_WRITE_MAX = 10 * 1024 * 1024
_LIST_LIMIT = 1000
_LEGACY_PROJECT_ID_RE = __import__("re").compile(r"^[A-Za-z0-9_-]{1,64}$")


class ProjectCreate(BaseModel):
  model_config = ConfigDict(extra="forbid")

  name: str = Field(default="Untitled project", min_length=1, max_length=256)
  template_id: str = Field(default="blank", min_length=1, max_length=128)
  recovery_request_id: str | None = Field(default=None, min_length=1, max_length=128)

  @field_validator("name")
  @classmethod
  def clean_name(cls, value: str) -> str:
    value = value.strip()
    if not value:
      raise ValueError("name must not be blank")
    return value


class ProjectPatch(BaseModel):
  model_config = ConfigDict(extra="forbid")

  name: str | None = Field(default=None, min_length=1, max_length=256)
  chat_id: str | None = Field(default=None, min_length=1, max_length=64)

  @field_validator("name")
  @classmethod
  def clean_name(cls, value: str | None) -> str | None:
    if value is None:
      return None
    value = value.strip()
    if not value:
      raise ValueError("name must not be blank")
    return value


class LegacyImport(BaseModel):
  model_config = ConfigDict(extra="forbid")

  app_id: int = Field(gt=0)
  legacy_project_id: str = Field(min_length=1, max_length=64)
  name: str | None = Field(default=None, max_length=256)

  @field_validator("legacy_project_id")
  @classmethod
  def valid_legacy_id(cls, value: str) -> str:
    if value != "default" and not _LEGACY_PROJECT_ID_RE.fullmatch(value):
      raise ValueError("legacy_project_id must be `default` or a project slug")
    return value


class FileWrite(BaseModel):
  model_config = ConfigDict(extra="forbid")

  content: str = Field(max_length=_WRITE_MAX)


def _project_response(project: models.Project) -> dict[str, Any]:
  return {
    "id": project.id,
    "name": project.name,
    "project_type": project.project_type,
    "chat_id": project.chat_id,
    "source_app_id": project.source_app_id,
    "template": project.template_snapshot_json or {},
    "legacy_source": project.legacy_source_json,
    "created_at": project.created_at,
    "updated_at": project.updated_at,
  }


def _live_project(db: Session, project_id: str) -> models.Project:
  project = db.query(models.Project).filter(
    models.Project.id == project_id,
    models.Project.deleted_at.is_(None),
  ).first()
  if project is None:
    raise HTTPException(404, "Project not found.")
  return project


def _project_root(project: models.Project) -> Path:
  data_root = Path(get_settings().data_dir).resolve()
  stored = Path(project.root_path)
  # Absolute values are accepted only as a rolling-upgrade compatibility path;
  # all new rows store a logical locator so moving the data volume preserves it.
  root = (stored if stored.is_absolute() else data_root / stored).resolve()
  try:
    root.relative_to(data_root)
  except ValueError as exc:
    raise HTTPException(500, "Project root is outside the data directory.") from exc
  return root


def _resolve_project_path(project: models.Project, path: str) -> tuple[Path, Path]:
  if "\x00" in (path or ""):
    raise HTTPException(400, "Invalid path.")
  root = _project_root(project)
  try:
    target = validate_path_within_base((path or "").lstrip("/"), root)
  except ValueError as exc:
    raise HTTPException(400, "Invalid project path.") from exc
  # A symlink is never an acceptable project boundary. resolve() confinement
  # prevents escape; refusing the link itself also keeps listings predictable.
  candidate = root / (path or "").lstrip("/")
  if candidate.is_symlink():
    raise HTTPException(403, "Symbolic links are not available in Projects.")
  return root, target


def _template_key(template: dict, app: models.App | None) -> str:
  if app is None:
    return "blank"
  return f"{app.slug}:{template.get('id')}"


def _safe_template(template: dict, app: models.App | None = None) -> dict:
  return {
    "key": _template_key(template, app),
    "id": str(template.get("id") or "blank"),
    "name": str(template.get("name") or "Blank project"),
    "description": str(template.get("description") or ""),
    "guidance": str(template.get("guidance") or ""),
    "skills": [str(value) for value in template.get("skills") or []],
    "dependencies": [str(value) for value in template.get("dependencies") or []],
    "previews": [
      {
        "id": str(value.get("id") or "preview"),
        "name": str(value.get("name") or "Preview"),
        "kind": str(value.get("kind") or "html"),
        "path": str(value.get("path") or ""),
      }
      for value in template.get("previews") or []
      if isinstance(value, dict)
    ],
    "actions": [
      {
        "id": str(value.get("id") or "action"),
        "name": str(value.get("name") or "Run"),
        "prompt": str(value.get("prompt") or ""),
      }
      for value in template.get("actions") or []
      if isinstance(value, dict)
    ],
    "files": dict(template.get("files") or {}),
    "source_app_id": app.id if app is not None else None,
    "source_app_name": app.name if app is not None else None,
    "source_app_version": app.version if app is not None else None,
  }


def _templates(db: Session) -> list[tuple[dict, models.App | None]]:
  rows: list[tuple[dict, models.App | None]] = [({
    "id": "blank",
    "name": "Blank project",
    "description": "Start with an empty folder and a project-aware chat.",
    "guidance": "Work only inside this project's root unless the user asks otherwise.",
    "skills": [],
    "dependencies": [],
    "files": {},
  }, None)]
  apps = db.query(models.App).options(
    defer(models.App.jsx_source),
    defer(models.App.icon_png),
    defer(models.App.icon_override_png),
  ).filter(
    models.App.deleted_at.is_(None),
    models.App.project_templates_json.isnot(None),
  ).order_by(models.App.name, models.App.id).all()
  for app in apps:
    for template in app.project_templates_json or []:
      if isinstance(template, dict):
        rows.append((template, app))
  return rows


def _template_by_id(db: Session, template_id: str) -> tuple[dict, models.App | None]:
  matches = [row for row in _templates(db) if _template_key(*row) == template_id]
  if not matches:
    raise HTTPException(422, "That project type is not installed.")
  return matches[0]


def _new_chat(db: Session, *, chat_id: str, title: str, owner: models.Owner) -> models.Chat:
  provider = providers.resolve_default_provider(
    get_settings().data_dir, owner.provider if owner else None,
  )
  return models.Chat(
    id=chat_id,
    title=title,
    messages=[],
    provider=provider,
    agent_settings_json=None,
    auto_resume_on_limit=bool(owner.auto_resume_on_limit_default),
    auto_resume_on_restart=bool(owner.auto_resume_on_restart_default),
  )


def _copy_template_files(root: Path, template: dict, app: models.App | None) -> None:
  files = template.get("files") or {}
  if not files:
    return
  if app is None:
    raise HTTPException(422, "Blank projects cannot declare template files.")
  app_root = Path(app.source_dir).resolve()
  for destination, source in files.items():
    source_path = validate_path_within_base(source, app_root)
    if not source_path.is_file() or source_path.is_symlink():
      raise HTTPException(409, f"Project template file is unavailable: {source}")
    target = validate_path_within_base(destination, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target)


@router.get("/templates")
def list_project_templates(
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  return [_safe_template(template, app) for template, app in _templates(db)]


@router.get("")
def list_projects(
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  rows = db.query(models.Project).filter(
    models.Project.deleted_at.is_(None),
  ).order_by(models.Project.updated_at.desc(), models.Project.created_at.desc()).all()
  return [_project_response(row) for row in rows]


@router.post("", dependencies=[Depends(reject_cross_site)])
def create_project(
  body: ProjectCreate,
  owner: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  with PROJECT_LIFECYCLE_LOCK:
    template, app = _template_by_id(db, body.template_id)
    if body.recovery_request_id:
      project_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL, f"mobius:project:{body.recovery_request_id}",
      ))
      chat_id = str(uuid.uuid5(uuid.UUID(project_id), "primary-chat"))
      existing = db.query(models.Project).filter(models.Project.id == project_id).first()
      if existing is not None:
        if existing.deleted_at is not None:
          raise HTTPException(409, "Project was deleted.")
        return _project_response(existing)
    else:
      project_id = str(uuid.uuid4())
      chat_id = str(uuid.uuid4())

    root_locator = Path("projects") / project_id
    root = (Path(get_settings().data_dir) / root_locator).resolve()
    if root.exists():
      raise HTTPException(409, "Project root already exists.")
    root.mkdir(parents=True)
    try:
      _copy_template_files(root, template, app)
      snapshot = _safe_template(template, app)
      chat = _new_chat(db, chat_id=chat_id, title=body.name, owner=owner)
      project = models.Project(
        id=project_id,
        name=body.name,
        project_type=_template_key(template, app),
        root_path=root_locator.as_posix(),
        chat_id=chat_id,
        source_app_id=app.id if app is not None else None,
        template_snapshot_json=snapshot,
      )
      db.add(chat)
      db.add(project)
      db.commit()
    except Exception:
      db.rollback()
      shutil.rmtree(root, ignore_errors=True)
      raise
  db.refresh(project)
  return _project_response(project)


def _legacy_storage_root(app: models.App, legacy_id: str) -> Path:
  data_root = Path(get_settings().data_dir).resolve()
  app_storage = (data_root / "apps" / str(app.id)).resolve()
  base = app_storage if legacy_id == "default" else app_storage / "projects" / legacy_id
  root = (base / "files").resolve()
  try:
    root.relative_to(app_storage)
  except ValueError as exc:
    raise HTTPException(400, "Invalid legacy project root.") from exc
  return root


def _read_legacy_projects(app: models.App) -> list[dict]:
  storage = Path(get_settings().data_dir) / "apps" / str(app.id)
  metadata: dict[str, str] = {}
  try:
    raw = json.loads((storage / "projects.json").read_text(encoding="utf-8"))
    if isinstance(raw, list):
      for row in raw:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
          metadata[row["id"]] = str(row.get("name") or row["id"])
  except (OSError, ValueError, TypeError):
    pass
  ids = set(metadata)
  if (storage / "files").is_dir():
    ids.add("default")
  projects_dir = storage / "projects"
  if projects_dir.is_dir():
    for child in projects_dir.iterdir():
      if child.is_dir() and not child.is_symlink() and _LEGACY_PROJECT_ID_RE.fullmatch(child.name):
        ids.add(child.name)
  return [
    {"legacy_project_id": project_id, "name": metadata.get(project_id) or (
      "Default project" if project_id == "default" else project_id.replace("-", " ").title()
    )}
    for project_id in sorted(ids, key=lambda value: (value != "default", value))
    if _legacy_storage_root(app, project_id).is_dir()
  ]


@router.get("/legacy")
def list_legacy_projects(
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  imported = {
    (int(source.get("app_id")), str(source.get("project_id")))
    for (source,) in db.query(models.Project.legacy_source_json).filter(
      models.Project.legacy_source_json.isnot(None),
    ).all()
    if isinstance(source, dict) and source.get("app_id") is not None
  }
  out = []
  apps = db.query(models.App).filter(
    models.App.deleted_at.is_(None),
    models.App.slug.in_(("latex", "webstudio")),
  ).order_by(models.App.name).all()
  for app in apps:
    for row in _read_legacy_projects(app):
      key = (app.id, row["legacy_project_id"])
      out.append({
        **row,
        "app_id": app.id,
        "app_name": app.name,
        "imported": key in imported,
      })
  return out


def _legacy_chat_id(app: models.App, legacy_id: str, db: Session) -> str | None:
  storage = Path(get_settings().data_dir) / "apps" / str(app.id)
  base = storage if legacy_id == "default" else storage / "projects" / legacy_id
  try:
    raw = json.loads((base / "chat_id.json").read_text(encoding="utf-8"))
  except (OSError, ValueError, TypeError):
    return None
  value = raw.get("id") if isinstance(raw, dict) else None
  if not isinstance(value, str):
    return None
  chat = db.query(models.Chat).filter(
    models.Chat.id == value,
    models.Chat.deleted_at.is_(None),
  ).first()
  if chat is None:
    return None
  linked = db.query(models.Project.id).filter(models.Project.chat_id == value).first()
  return None if linked else value


@router.post("/import-legacy", dependencies=[Depends(reject_cross_site)])
def import_legacy_project(
  body: LegacyImport,
  owner: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  app = db.query(models.App).filter(
    models.App.id == body.app_id,
    models.App.deleted_at.is_(None),
  ).first()
  if app is None or app.slug not in ("latex", "webstudio"):
    raise HTTPException(404, "Compatible legacy app not found.")
  root = _legacy_storage_root(app, body.legacy_project_id)
  if not root.is_dir():
    raise HTTPException(404, "Legacy project files were not found.")
  for project in db.query(models.Project).filter(
    models.Project.legacy_source_json.isnot(None),
  ).all():
    source = project.legacy_source_json or {}
    if source.get("app_id") == app.id and source.get("project_id") == body.legacy_project_id:
      if project.deleted_at is not None:
        raise HTTPException(409, "This imported project is in recovery.")
      return _project_response(project)

  legacy_rows = _read_legacy_projects(app)
  legacy = next(
    (row for row in legacy_rows if row["legacy_project_id"] == body.legacy_project_id),
    None,
  )
  name = (body.name or (legacy or {}).get("name") or body.legacy_project_id).strip()
  templates = app.project_templates_json or []
  template = next((row for row in templates if isinstance(row, dict)), {
    "id": app.slug,
    "name": app.name,
    "description": app.description,
    "skills": [],
    "dependencies": [],
    "files": {},
  })
  project_id = str(uuid.uuid5(
    uuid.NAMESPACE_URL,
    f"mobius:legacy-project:{app.id}:{body.legacy_project_id}",
  ))
  chat_id = _legacy_chat_id(app, body.legacy_project_id, db)
  if chat_id is None:
    chat_id = str(uuid.uuid5(uuid.UUID(project_id), "primary-chat"))
    db.add(_new_chat(db, chat_id=chat_id, title=name, owner=owner))
  project = models.Project(
    id=project_id,
    name=name,
    project_type=_template_key(template, app),
    root_path=root.relative_to(Path(get_settings().data_dir).resolve()).as_posix(),
    chat_id=chat_id,
    source_app_id=app.id,
    template_snapshot_json=_safe_template(template, app),
    legacy_source_json={
      "app_id": app.id,
      "project_id": body.legacy_project_id,
      "storage_root": root.parent.relative_to(
        Path(get_settings().data_dir).resolve(),
      ).as_posix(),
    },
  )
  db.add(project)
  try:
    db.commit()
  except IntegrityError:
    db.rollback()
    existing = db.query(models.Project).filter(models.Project.id == project_id).first()
    if existing is not None:
      return _project_response(existing)
    raise
  db.refresh(project)
  return _project_response(project)


@router.get("/{project_id}")
def get_project(
  project_id: str,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  return _project_response(_live_project(db, project_id))


@router.patch("/{project_id}", dependencies=[Depends(reject_cross_site)])
def patch_project(
  project_id: str,
  body: ProjectPatch,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  project = _live_project(db, project_id)
  if body.name is not None:
    project.name = body.name
  if body.chat_id is not None and body.chat_id != project.chat_id:
    chat = db.query(models.Chat).filter(
      models.Chat.id == body.chat_id,
      models.Chat.deleted_at.is_(None),
      models.Chat.created_by_app_id.is_(None),
    ).first()
    if chat is None:
      raise HTTPException(422, "Replacement chat must be a live owner chat.")
    occupied = db.query(models.Project.id).filter(
      models.Project.chat_id == body.chat_id,
      models.Project.id != project.id,
    ).first()
    if occupied:
      raise HTTPException(409, "That chat already belongs to another project.")
    project.chat_id = body.chat_id
  try:
    db.commit()
  except IntegrityError as exc:
    db.rollback()
    raise HTTPException(409, "Project chat is already in use.") from exc
  db.refresh(project)
  return _project_response(project)


@router.delete(
  "/{project_id}", status_code=204, dependencies=[Depends(reject_cross_site)],
)
async def delete_project(
  project_id: str,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  project = _live_project(db, project_id)
  chat = db.query(models.Chat).filter(
    models.Chat.id == project.chat_id,
    models.Chat.deleted_at.is_(None),
  ).first()
  if chat is None:
    raise HTTPException(409, "Project primary chat is unavailable.")
  if is_chat_running(chat.id):
    try:
      stopped, _ = await stop_chat_for(chat.id, db=db)
    except Exception:
      log.warning("Failed to stop project chat %s during delete", chat.id)
      stopped = False
    if not stopped:
      raise HTTPException(409, "Could not stop the active project agent; retry.")
  # One tombstone timestamp and one commit make project + primary chat a single
  # recovery unit. The root remains untouched throughout the recovery window.
  bump_run_generation(chat.id)
  with PROJECT_LIFECYCLE_LOCK:
    deleted_at = now_naive_utc()
    project.deleted_at = deleted_at
    chat.deleted_at = deleted_at
    db.commit()
  questions.cancel(chat.id)
  mark_chat_deleted(chat.id)
  try:
    await _finish_run(chat.id, terminal_status="stopped")
  except Exception:
    log.exception(
      "Project %s was deleted but chat %s run cleanup failed",
      project.id, chat.id,
    )
  get_system_broadcast().publish(
    {"type": "chat_deleted", "chatId": str(chat.id)}
  )
  get_system_broadcast().publish({
    "type": "project_deleted",
    "projectId": str(project.id),
    "chatId": str(chat.id),
  })
  return Response(status_code=204)


@router.post("/{project_id}/recover", dependencies=[Depends(reject_cross_site)])
def recover_project(
  project_id: str,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  with PROJECT_LIFECYCLE_LOCK:
    project = db.query(models.Project).filter(
      models.Project.id == project_id,
      models.Project.deleted_at.isnot(None),
    ).first()
    if project is None:
      raise HTTPException(404, "Project not found or not deleted.")
    if now_naive_utc() - project.deleted_at >= SOFT_DELETE_TTL:
      raise HTTPException(410, "Recovery window has expired.")
    chat = db.query(models.Chat).filter(models.Chat.id == project.chat_id).first()
    if chat is None or not _project_root(project).is_dir():
      raise HTTPException(409, "Project chat or files are unavailable.")
    project.deleted_at = None
    chat.deleted_at = None
    db.commit()
  recover_chat_generation(chat.id)
  get_system_broadcast().publish(
    {"type": "chat_recovered", "chatId": str(chat.id)}
  )
  get_system_broadcast().publish({
    "type": "project_recovered",
    "projectId": str(project.id),
    "chatId": str(chat.id),
  })
  return _project_response(project)


@router.get("/{project_id}/files")
def list_project_files(
  project_id: str,
  path: str = Query(default="", max_length=2048),
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  project = _live_project(db, project_id)
  root, directory = _resolve_project_path(project, path)
  if not directory.exists():
    return {"path": path, "entries": []}
  if not directory.is_dir():
    raise HTTPException(400, "Path is not a directory.")
  entries = []
  for child in sorted(directory.iterdir(), key=lambda value: (not value.is_dir(), value.name.lower())):
    if len(entries) >= _LIST_LIMIT:
      break
    if child.is_symlink():
      continue
    rel = child.relative_to(root).as_posix()
    stat = child.stat()
    entries.append({
      "name": child.name,
      "path": rel,
      "type": "directory" if child.is_dir() else "file",
      "size": 0 if child.is_dir() else stat.st_size,
      "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
      "mime_type": None if child.is_dir() else mimetypes.guess_type(child.name)[0],
    })
  return {"path": path, "entries": entries, "truncated": len(entries) >= _LIST_LIMIT}


@router.get("/{project_id}/file")
def read_project_file(
  project_id: str,
  path: str = Query(min_length=1, max_length=2048),
  download: bool = False,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  project = _live_project(db, project_id)
  _root, target = _resolve_project_path(project, path)
  if not target.is_file():
    raise HTTPException(404, "File not found.")
  if target.stat().st_size > _READ_MAX:
    raise HTTPException(413, "File is too large to open in Projects.")
  media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
  if not download and (
    media_type.startswith("text/")
    or media_type in ("application/json", "application/javascript", "image/svg+xml")
  ):
    try:
      return {"path": path, "content": target.read_text(encoding="utf-8"), "mime_type": media_type}
    except UnicodeDecodeError:
      pass
  return FileResponse(target, media_type=media_type, filename=target.name if download else None)


@router.put(
  "/{project_id}/file", dependencies=[Depends(reject_cross_site)],
)
def write_project_file(
  project_id: str,
  body: FileWrite,
  path: str = Query(min_length=1, max_length=2048),
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  project = _live_project(db, project_id)
  root, target = _resolve_project_path(project, path)
  if target == root:
    raise HTTPException(400, "A project root is not a file.")
  target.parent.mkdir(parents=True, exist_ok=True)
  encoded = body.content.encode("utf-8")
  if len(encoded) > _WRITE_MAX:
    raise HTTPException(413, "File is too large to save in Projects.")
  temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
  try:
    temp.write_bytes(encoded)
    os.replace(temp, target)
  finally:
    try:
      temp.unlink()
    except FileNotFoundError:
      pass
  project.updated_at = now_naive_utc()
  db.commit()
  return {"ok": True, "path": target.relative_to(root).as_posix()}


@router.put(
  "/{project_id}/file-bytes", dependencies=[Depends(reject_cross_site)],
)
async def write_project_file_bytes(
  project_id: str,
  request: Request,
  path: str = Query(min_length=1, max_length=2048),
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  """Write an image/PDF/asset without coercing it through JSON text."""
  length = request.headers.get("content-length")
  if length:
    try:
      parsed_length = int(length)
    except ValueError as exc:
      raise HTTPException(400, "Invalid Content-Length header.") from exc
    if parsed_length < 0:
      raise HTTPException(400, "Invalid Content-Length header.")
    if parsed_length > _WRITE_MAX:
      raise HTTPException(413, "File is too large to save in Projects.")
  content = await request.body()
  if len(content) > _WRITE_MAX:
    raise HTTPException(413, "File is too large to save in Projects.")
  project = _live_project(db, project_id)
  root, target = _resolve_project_path(project, path)
  if target == root:
    raise HTTPException(400, "A project root is not a file.")
  target.parent.mkdir(parents=True, exist_ok=True)
  temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
  try:
    temp.write_bytes(content)
    os.replace(temp, target)
  finally:
    try:
      temp.unlink()
    except FileNotFoundError:
      pass
  project.updated_at = now_naive_utc()
  db.commit()
  return {"ok": True, "path": target.relative_to(root).as_posix()}


@router.delete(
  "/{project_id}/file", dependencies=[Depends(reject_cross_site)],
)
def delete_project_file(
  project_id: str,
  path: str = Query(min_length=1, max_length=2048),
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  project = _live_project(db, project_id)
  root, target = _resolve_project_path(project, path)
  if target == root:
    raise HTTPException(400, "The project root cannot be deleted.")
  if target.is_dir():
    shutil.rmtree(target)
  elif target.is_file():
    target.unlink()
  else:
    raise HTTPException(404, "File not found.")
  project.updated_at = now_naive_utc()
  db.commit()
  return {"ok": True}
