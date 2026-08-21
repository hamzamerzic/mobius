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
from sqlalchemy.orm.attributes import flag_modified

from app import models, project_builders, providers, questions
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
from app.deps import get_current_owner, reject_cross_site, resolve_owner_only
from app.path_utils import validate_path_within_base
from app.project_retention import PROJECT_LIFECYCLE_LOCK
from app.timeutil import now_naive_utc, SOFT_DELETE_TTL


router = APIRouter(prefix="/api/projects", tags=["projects"])
log = logging.getLogger(__name__)

_READ_MAX = 10 * 1024 * 1024
_WRITE_MAX = 10 * 1024 * 1024
_LIST_LIMIT = 1000
# Tail window returned by the build-log endpoint. The on-disk log is bounded
# separately by project_builders; this caps what a single read returns.
_LOG_TAIL_MAX = 64 * 1024
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

  @field_validator("name")
  @classmethod
  def clean_name(cls, value: str | None) -> str | None:
    if value is None:
      return None
    value = value.strip()
    if not value:
      raise ValueError("name must not be blank")
    return value


class ProjectChatCreate(BaseModel):
  model_config = ConfigDict(extra="forbid")

  title: str = Field(default="New chat", min_length=1, max_length=256)
  recovery_request_id: str | None = Field(default=None, min_length=1, max_length=128)

  @field_validator("title")
  @classmethod
  def clean_title(cls, value: str) -> str:
    value = value.strip()
    if not value:
      raise ValueError("title must not be blank")
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


class FolderCreate(BaseModel):
  model_config = ConfigDict(extra="forbid")

  path: str = Field(min_length=1, max_length=2048)


class PathMove(BaseModel):
  model_config = ConfigDict(extra="forbid")

  from_path: str = Field(min_length=1, max_length=2048)
  to_path: str = Field(min_length=1, max_length=2048)


class ArtifactCreate(BaseModel):
  model_config = ConfigDict(extra="forbid")

  name: str = Field(min_length=1, max_length=256)
  builder: str = Field(min_length=1, max_length=32)
  source: str = Field(min_length=1, max_length=2048)
  # Optional caller-chosen id; otherwise derived from the name. Validated
  # against the slug charset before it is used as a path component.
  id: str | None = Field(default=None, min_length=1, max_length=64)

  @field_validator("name")
  @classmethod
  def clean_name(cls, value: str) -> str:
    value = value.strip()
    if not value:
      raise ValueError("name must not be blank")
    return value


def _project_response(
  project: models.Project, chats: list[models.Chat] | None = None,
) -> dict[str, Any]:
  return {
    "id": project.id,
    "name": project.name,
    "project_type": project.project_type,
    "chat_id": project.chat_id,
    "source_app_id": project.source_app_id,
    "template": project.template_snapshot_json or {},
    "legacy_source": project.legacy_source_json,
    "artifacts": _project_artifacts_view(project),
    "created_at": project.created_at,
    "updated_at": project.updated_at,
    "chats": [_project_chat_response(chat) for chat in (chats or [])],
  }


def _project_chat_response(chat: models.Chat) -> dict[str, Any]:
  return {
    "id": chat.id,
    "title": chat.title,
    "has_messages": bool(chat.has_messages),
    "provider": chat.provider,
    "created_at": chat.created_at,
    "updated_at": chat.updated_at,
    "activity_at": chat.activity_at,
  }


def _live_project_chat_rows(db: Session, project_id: str) -> list[models.Chat]:
  return db.query(models.Chat).filter(
    models.Chat.project_id == project_id,
    models.Chat.deleted_at.is_(None),
  ).order_by(
    models.Chat.activity_at.desc(),
    models.Chat.updated_at.desc(),
    models.Chat.created_at.desc(),
  ).all()


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


def _artifacts_root(root: Path) -> Path:
  """The reserved build-output area under a project root."""
  return (root / "artifacts").resolve()


def _within_artifacts(root: Path, path: Path) -> bool:
  """Whether a resolved path is the reserved artifacts area or inside it."""
  return path.resolve().is_relative_to(_artifacts_root(root))


def _artifact_view(
  project_id: str, root: Path, entry: dict[str, Any],
) -> dict[str, Any]:
  """Owner-facing artifact row: registry fields plus reconciled/derived state.

  Lenient by construction — a hand-edited entry with a missing source or an
  unknown builder surfaces ``source_missing`` / a null builder rather than
  raising. ``status`` is reconciled against the live task registry so a stale
  ``building`` reads as ``error`` and a queued build reads as ``building``.
  """
  artifact_id = entry.get("id")
  builder = entry.get("builder")
  source = entry.get("source")
  output_rel = entry.get("output_rel")
  if not (isinstance(output_rel, str) and output_rel):
    output_rel = project_builders.default_output_rel(
      str(artifact_id), str(builder), str(source or ""),
    )
  log_rel = entry.get("log_rel")
  if not (isinstance(log_rel, str) and log_rel):
    log_rel = project_builders.default_log_rel(str(artifact_id))
  source_exists = bool(
    isinstance(source, str) and source and (root / source.lstrip("/")).is_file()
  )
  has_output = False
  try:
    output_path = (root / output_rel.lstrip("/")).resolve()
    if _within_artifacts(root, output_path) and output_path.is_file():
      has_output = True
  except (OSError, ValueError):
    has_output = False
  return {
    "id": artifact_id,
    "name": entry.get("name") or artifact_id,
    "builder": builder if builder in project_builders.BUILDERS else None,
    "source": source,
    "output_rel": output_rel,
    "log_rel": log_rel,
    "status": project_builders.effective_status(project_id, entry),
    "updated_at": entry.get("updated_at"),
    "duration_ms": entry.get("duration_ms"),
    "has_output": has_output,
    "source_missing": not source_exists,
  }


def _project_artifacts_view(project: models.Project) -> list[dict[str, Any]]:
  """Artifact rows for a project payload; never raises into the response."""
  try:
    root = _project_root(project)
  except HTTPException:
    return []
  return [
    _artifact_view(project.id, root, entry)
    for entry in project_builders.read_artifacts(project)
  ]


def _previews_to_artifacts(
  snapshot: dict, root: Path,
) -> list[dict[str, Any]]:
  """Map a template's website/latex previews to buildable artifact entries.

  A preview declares its OUTPUT path and kind; the artifact needs the SOURCE.
  A pdf preview (``main.pdf``) builds from the matching ``.tex`` source; an
  html preview's path is both source and output entry. A preview is registered
  only when its mapped source file actually exists in the freshly scaffolded
  project, so no artifact points at a file that was never copied.
  """
  artifacts: list[dict[str, Any]] = []
  seen: set[str] = set()
  for preview in snapshot.get("previews") or []:
    if not isinstance(preview, dict):
      continue
    kind = str(preview.get("kind") or "").lower()
    output_path = str(preview.get("path") or "").lstrip("/")
    if not output_path:
      continue
    if kind == "pdf":
      builder = "latex"
      source = Path(output_path).with_suffix(".tex").as_posix()
    elif kind in ("html", "website"):
      builder = "website"
      source = output_path
    else:
      continue
    if not (root / source).is_file():
      continue
    artifact_id = project_builders.slug_artifact_id(
      str(preview.get("id") or preview.get("name") or builder),
    )
    if not project_builders.ARTIFACT_ID_RE.match(artifact_id) or artifact_id in seen:
      continue
    seen.add(artifact_id)
    artifacts.append(project_builders.new_artifact_entry(
      artifact_id,
      str(preview.get("name") or artifact_id),
      builder,
      source,
    ))
  return artifacts


def _resolve_output_owner(
  request: Request,
  db: Session = Depends(get_db),
) -> models.Owner:
  """Owner auth for the artifact-output GET (Authorization: Bearer only).

  The shell always fetches artifact output through the owner's Bearer header:
  pdfjs for a latex document, and for a website the shell fetches the built
  files and inlines them into a sandboxed ``srcDoc``. The owner token is never
  carried on the URL, so a sandboxed artifact's JS cannot read it from
  ``window.location``. App-scoped tokens are rejected (owner-only).
  """
  authorization = request.headers.get("Authorization", "")
  scheme, _, header_token = authorization.partition(" ")
  if scheme.lower() != "bearer" or not header_token:
    raise HTTPException(401, "Not authenticated.")
  return resolve_owner_only(header_token, db)


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
    "description": "Start with an empty folder.",
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


def _new_chat(
  db: Session, *, chat_id: str, title: str, owner: models.Owner,
  project_id: str | None = None,
) -> models.Chat:
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
    project_id=project_id,
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
  project_ids = [row.id for row in rows]
  chats_by_project: dict[str, list[models.Chat]] = {
    project_id: [] for project_id in project_ids
  }
  if project_ids:
    chat_rows = db.query(models.Chat).filter(
      models.Chat.project_id.in_(project_ids),
      models.Chat.deleted_at.is_(None),
    ).order_by(
      models.Chat.activity_at.desc(),
      models.Chat.updated_at.desc(),
      models.Chat.created_at.desc(),
    ).all()
    for chat in chat_rows:
      chats_by_project.setdefault(str(chat.project_id), []).append(chat)
  return [
    _project_response(row, chats_by_project.get(str(row.id), [])) for row in rows
  ]


@router.post("", dependencies=[Depends(reject_cross_site)])
def create_project(
  body: ProjectCreate,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  with PROJECT_LIFECYCLE_LOCK:
    template, app = _template_by_id(db, body.template_id)
    if body.recovery_request_id:
      project_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL, f"mobius:project:{body.recovery_request_id}",
      ))
      existing = db.query(models.Project).filter(models.Project.id == project_id).first()
      if existing is not None:
        if existing.deleted_at is not None:
          raise HTTPException(409, "Project was deleted.")
        return _project_response(existing)
    else:
      project_id = str(uuid.uuid4())

    root_locator = Path("projects") / project_id
    root = (Path(get_settings().data_dir) / root_locator).resolve()
    if root.exists():
      raise HTTPException(409, "Project root already exists.")
    root.mkdir(parents=True)
    try:
      _copy_template_files(root, template, app)
      snapshot = _safe_template(template, app)
      # A template's website/latex previews become buildable artifacts up
      # front, so a new project is never left half-wired: the file grid, the
      # artifact list, and the build button all reference the same registry.
      artifacts = _previews_to_artifacts(snapshot, root)
      project = models.Project(
        id=project_id,
        name=body.name,
        project_type=_template_key(template, app),
        root_path=root_locator.as_posix(),
        chat_id=None,
        source_app_id=app.id if app is not None else None,
        template_snapshot_json=snapshot,
        artifacts_json=artifacts or None,
      )
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
  linked = db.query(models.Project.id).filter(
    (models.Project.chat_id == value)
    | (models.Project.id == chat.project_id)
  ).first()
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
      return _project_response(project, _live_project_chat_rows(db, project.id))

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
  legacy_chat = db.get(models.Chat, chat_id) if chat_id else None
  if legacy_chat is not None:
    legacy_chat.project_id = project_id
  project = models.Project(
    id=project_id,
    name=name,
    project_type=_template_key(template, app),
    root_path=root.relative_to(Path(get_settings().data_dir).resolve()).as_posix(),
    chat_id=None,
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
      return _project_response(existing, _live_project_chat_rows(db, existing.id))
    raise
  db.refresh(project)
  return _project_response(
    project, [legacy_chat] if legacy_chat is not None else [],
  )


@router.get("/{project_id}/chats")
def list_project_chats(
  project_id: str,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  _live_project(db, project_id)
  rows = _live_project_chat_rows(db, project_id)
  return [_project_chat_response(row) for row in rows]


@router.post(
  "/{project_id}/chats", status_code=201,
  dependencies=[Depends(reject_cross_site)],
)
def create_project_chat(
  project_id: str,
  body: ProjectChatCreate,
  owner: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  project = _live_project(db, project_id)
  chat_id = (
    str(uuid.uuid5(uuid.UUID(project.id), body.recovery_request_id))
    if body.recovery_request_id
    else str(uuid.uuid4())
  )
  existing = db.get(models.Chat, chat_id)
  if existing is not None:
    if existing.deleted_at is not None:
      raise HTTPException(409, "Project chat was deleted.")
    if existing.project_id != project.id:
      raise HTTPException(409, "Chat identity is already in use.")
    return _project_chat_response(existing)
  chat = _new_chat(
    db, chat_id=chat_id, title=body.title, owner=owner,
    project_id=project.id,
  )
  db.add(chat)
  project.updated_at = now_naive_utc()
  try:
    db.commit()
  except IntegrityError:
    db.rollback()
    existing = db.get(models.Chat, chat_id)
    if existing is None or existing.project_id != project.id:
      raise
    return _project_chat_response(existing)
  db.refresh(chat)
  get_system_broadcast().publish({
    "type": "project_chat_created",
    "projectId": str(project.id),
    "chatId": str(chat.id),
  })
  return _project_chat_response(chat)


@router.get("/{project_id}")
def get_project(
  project_id: str,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  project = _live_project(db, project_id)
  chats = _live_project_chat_rows(db, project.id)
  return _project_response(project, chats)


@router.post(
  "/{project_id}/folder", dependencies=[Depends(reject_cross_site)],
)
def create_project_folder(
  project_id: str,
  body: FolderCreate,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  project = _live_project(db, project_id)
  root, target = _resolve_project_path(project, body.path)
  if target == root:
    raise HTTPException(400, "The project root already exists.")
  try:
    target.mkdir(parents=True, exist_ok=False)
  except FileExistsError as exc:
    raise HTTPException(409, "A file or folder already uses that path.") from exc
  project.updated_at = now_naive_utc()
  db.commit()
  return {"ok": True, "path": target.relative_to(root).as_posix()}


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
  try:
    db.commit()
  except IntegrityError as exc:
    db.rollback()
    raise HTTPException(409, "Project could not be updated.") from exc
  db.refresh(project)
  return _project_response(project, _live_project_chat_rows(db, project.id))


@router.delete(
  "/{project_id}", status_code=204, dependencies=[Depends(reject_cross_site)],
)
async def delete_project(
  project_id: str,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  project = _live_project(db, project_id)
  chats = db.query(models.Chat).filter(
    models.Chat.project_id == project.id,
    models.Chat.deleted_at.is_(None),
  ).all()
  for chat in chats:
    if is_chat_running(chat.id):
      try:
        stopped, _ = await stop_chat_for(chat.id, db=db)
      except Exception:
        log.warning("Failed to stop project chat %s during delete", chat.id)
        stopped = False
      if not stopped:
        raise HTTPException(
          409, "Could not stop an active project agent; retry."
        )
  # One timestamp and one commit make the project and all currently-live chats
  # a recovery unit. Chats deleted earlier keep their own tombstone and are not
  # unexpectedly recovered with the project.
  for chat in chats:
    bump_run_generation(chat.id)
  with PROJECT_LIFECYCLE_LOCK:
    deleted_at = now_naive_utc()
    project.deleted_at = deleted_at
    for chat in chats:
      chat.deleted_at = deleted_at
    db.commit()
  for chat in chats:
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
    "chatIds": [str(chat.id) for chat in chats],
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
    if not _project_root(project).is_dir():
      raise HTTPException(409, "Project files are unavailable.")
    deleted_at = project.deleted_at
    chats = db.query(models.Chat).filter(
      models.Chat.project_id == project.id,
      models.Chat.deleted_at == deleted_at,
    ).all()
    project.deleted_at = None
    for chat in chats:
      chat.deleted_at = None
    db.commit()
  for chat in chats:
    recover_chat_generation(chat.id)
    get_system_broadcast().publish(
      {"type": "chat_recovered", "chatId": str(chat.id)}
    )
  get_system_broadcast().publish({
    "type": "project_recovered",
    "projectId": str(project.id),
    "chatIds": [str(chat.id) for chat in chats],
  })
  return _project_response(project, chats)


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
  at_root = directory.resolve() == root.resolve()
  entries = []
  for child in sorted(directory.iterdir(), key=lambda value: (not value.is_dir(), value.name.lower())):
    if len(entries) >= _LIST_LIMIT:
      break
    if child.is_symlink():
      continue
    # `artifacts/` at the root is managed build output surfaced in the Artifacts
    # zone, not source the owner edits — keep it out of the finder to avoid
    # clutter. It stays on disk and reachable via the artifact-output endpoint.
    if at_root and child.is_dir() and child.name == "artifacts":
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
    or media_type in (
      "application/json", "application/javascript", "application/x-latex",
      "application/x-tex", "image/svg+xml",
    )
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


@router.post(
  "/{project_id}/move", dependencies=[Depends(reject_cross_site)],
)
def move_project_path(
  project_id: str,
  body: PathMove,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  """Rename or move one confined file or directory within a project.

  Both endpoints resolve through ``_resolve_project_path`` (confinement +
  symlink rejection). The guards refuse moving the root, a missing source, an
  occupied destination, a folder into its own descendant, and any move touching
  the reserved ``artifacts/`` build-output area (managed by the artifact
  registry, not hand-moves). An ``os.replace`` failure maps to 409, never 500.
  """
  project = _live_project(db, project_id)
  root, source = _resolve_project_path(project, body.from_path)
  _root, dest = _resolve_project_path(project, body.to_path)
  if source == root or dest == root:
    raise HTTPException(400, "The project root cannot be moved.")
  if not source.exists():
    raise HTTPException(404, "Source path not found.")
  if dest.exists():
    raise HTTPException(409, "A file or folder already uses the destination.")
  if dest == source or dest.is_relative_to(source):
    raise HTTPException(400, "Cannot move a path into itself or a descendant.")
  if _within_artifacts(root, source) or _within_artifacts(root, dest):
    raise HTTPException(409, "The artifacts area is managed by builds.")
  dest.parent.mkdir(parents=True, exist_ok=True)
  try:
    os.replace(source, dest)
  except OSError as exc:
    raise HTTPException(409, "Could not move the path.") from exc
  project.updated_at = now_naive_utc()
  db.commit()
  return {
    "ok": True,
    "from": source.relative_to(root).as_posix(),
    "to": dest.relative_to(root).as_posix(),
  }


@router.get("/{project_id}/artifacts")
def list_project_artifacts(
  project_id: str,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  """List a project's artifacts, reconciling live/stale build status."""
  project = _live_project(db, project_id)
  root = _project_root(project)
  return {
    "artifacts": [
      _artifact_view(project.id, root, entry)
      for entry in project_builders.read_artifacts(project)
    ],
  }


@router.post(
  "/{project_id}/artifacts", status_code=201,
  dependencies=[Depends(reject_cross_site)],
)
async def create_project_artifact(
  project_id: str,
  body: ArtifactCreate,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  """Register a new buildable artifact.

  Async so its ``artifacts_json`` read-update-commit is ordered on the single
  event loop against a concurrent build's status write — the loop runs this
  handler with no ``await`` between the read and the commit, so neither write is
  lost. Validates the builder and that the source resolves to a real project
  file before recording it.
  """
  project = _live_project(db, project_id)
  root = _project_root(project)
  if body.builder not in project_builders.BUILDERS:
    raise HTTPException(422, "Unknown builder.")
  _root, source_path = _resolve_project_path(project, body.source)
  if not source_path.is_file():
    raise HTTPException(422, "Source file does not exist.")
  source_rel = source_path.relative_to(root).as_posix()
  artifact_id = body.id or project_builders.slug_artifact_id(body.name)
  if not project_builders.ARTIFACT_ID_RE.match(artifact_id):
    raise HTTPException(422, "Invalid artifact id.")
  entries = project_builders.read_artifacts(project)
  if any(entry.get("id") == artifact_id for entry in entries):
    raise HTTPException(409, "An artifact with that id already exists.")
  entry = project_builders.new_artifact_entry(
    artifact_id, body.name, body.builder, source_rel,
  )
  entries.append(entry)
  project.artifacts_json = entries
  flag_modified(project, "artifacts_json")
  project.updated_at = now_naive_utc()
  db.commit()
  return _artifact_view(project.id, root, entry)


@router.delete(
  "/{project_id}/artifacts/{artifact_id}", status_code=204,
  dependencies=[Depends(reject_cross_site)],
)
async def delete_project_artifact(
  project_id: str,
  artifact_id: str,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  """Remove an artifact entry and its on-disk ``artifacts/<id>/`` tree."""
  project = _live_project(db, project_id)
  root = _project_root(project)
  if not project_builders.ARTIFACT_ID_RE.match(artifact_id):
    raise HTTPException(400, "Invalid artifact id.")
  if project_builders.is_build_live(project.id, artifact_id):
    raise HTTPException(409, "A build is in progress for this artifact.")
  entries = project_builders.read_artifacts(project)
  remaining = [entry for entry in entries if entry.get("id") != artifact_id]
  if len(remaining) == len(entries):
    raise HTTPException(404, "Artifact not found.")
  artifact_dir = (root / "artifacts" / artifact_id).resolve()
  if _within_artifacts(root, artifact_dir) and artifact_dir != _artifacts_root(root):
    shutil.rmtree(artifact_dir, ignore_errors=True)
  project.artifacts_json = remaining or None
  flag_modified(project, "artifacts_json")
  project.updated_at = now_naive_utc()
  db.commit()
  return Response(status_code=204)


@router.post(
  "/{project_id}/artifacts/{artifact_id}/build",
  dependencies=[Depends(reject_cross_site)],
)
async def build_project_artifact(
  project_id: str,
  artifact_id: str,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  """Start a build for one artifact.

  409 only when a LIVE build task already exists for this artifact; a stale
  ``building`` marker (no live task) is reconciled and a rebuild is allowed.
  Returns the artifact row, which now reports ``building`` because the task is
  registered before this returns.
  """
  project = _live_project(db, project_id)
  root = _project_root(project)
  if not project_builders.ARTIFACT_ID_RE.match(artifact_id):
    raise HTTPException(400, "Invalid artifact id.")
  entry = next(
    (e for e in project_builders.read_artifacts(project)
     if e.get("id") == artifact_id),
    None,
  )
  if entry is None:
    raise HTTPException(404, "Artifact not found.")
  if entry.get("builder") not in project_builders.BUILDERS:
    raise HTTPException(422, "This artifact has an unknown builder.")
  source = entry.get("source")
  if not (isinstance(source, str) and (root / source.lstrip("/")).is_file()):
    raise HTTPException(422, "The artifact source file is missing.")
  if project_builders.is_build_live(project.id, artifact_id):
    raise HTTPException(409, "A build is already in progress.")
  project_builders.start_build(project.id, artifact_id)
  return _artifact_view(project.id, root, entry)


@router.get("/{project_id}/artifacts/{artifact_id}/log")
def read_project_artifact_log(
  project_id: str,
  artifact_id: str,
  _: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  """Return the tail of an artifact's build log (capped ~64 KB)."""
  project = _live_project(db, project_id)
  root = _project_root(project)
  if not project_builders.ARTIFACT_ID_RE.match(artifact_id):
    raise HTTPException(400, "Invalid artifact id.")
  log_path = (root / "artifacts" / artifact_id / "build.log").resolve()
  if not _within_artifacts(root, log_path):
    raise HTTPException(400, "Invalid artifact path.")
  if not log_path.is_file():
    return {"log": "", "truncated": False}
  data = log_path.read_bytes()
  truncated = len(data) > _LOG_TAIL_MAX
  tail = data[-_LOG_TAIL_MAX:]
  return {"log": tail.decode("utf-8", errors="replace"), "truncated": truncated}


@router.get("/{project_id}/artifacts/{artifact_id}/output/{path:path}")
def serve_project_artifact_output(
  project_id: str,
  artifact_id: str,
  path: str,
  _owner: models.Owner = Depends(_resolve_output_owner),
  db: Session = Depends(get_db),
):
  """Stream a confined artifact-output file.

  A dedicated FileResponse with NO 10 MB read cap — a real thesis PDF or a
  multi-asset website is large by design. Confined to ``artifacts/<id>/output/``
  with symlink rejection. A website entry (any served HTML) gets a strict
  per-response CSP so the sandboxed iframe cannot reach the shell token.
  """
  project = _live_project(db, project_id)
  root = _project_root(project)
  if not project_builders.ARTIFACT_ID_RE.match(artifact_id):
    raise HTTPException(400, "Invalid artifact id.")
  output_root = (root / "artifacts" / artifact_id / "output")
  rel = (path or "").lstrip("/")
  if "\x00" in rel:
    raise HTTPException(400, "Invalid path.")
  try:
    target = validate_path_within_base(rel, output_root)
  except ValueError as exc:
    raise HTTPException(400, "Invalid artifact output path.") from exc
  candidate = output_root / rel
  if candidate.is_symlink():
    raise HTTPException(403, "Symbolic links are not available in output.")
  if not target.is_file():
    raise HTTPException(404, "Artifact output not found.")
  media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
  # The per-response CSP for this namespace (the exact policy the spec gives) is
  # applied authoritatively by main._SecurityHeadersMiddleware — it strips any
  # CSP a route sets, so setting it here would be dead. See _ARTIFACT_OUTPUT_CSP.
  return FileResponse(target, media_type=media_type)
