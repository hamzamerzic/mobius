"""Same-origin BFF for the GitHub-backed Möbius community catalog."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import fs_locks, models
from app.community_broker import (
  COMMUNITY_PREFIX,
  CommunityBrokerError,
  community_broker,
)
from app.community_publish import CommunityPublicationError, build_public_snapshot
from app.database import get_db
from app.deps import get_owner_or_app_with_manage_apps, reject_cross_site


router = APIRouter(prefix="/api/community", tags=["community"])
_PUBLIC_IDENTITY = Literal["anonymous", "github"]
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9_:-]{8,200}$")


class PublishLocalAppIn(BaseModel):
  app_id: int = Field(gt=0)
  confirm_source_public: Literal[True]
  public_identity: _PUBLIC_IDENTITY = "anonymous"


class ExistingGitHubRevisionIn(BaseModel):
  repository: str = Field(min_length=3, max_length=200)
  commit_sha: str = Field(pattern=r"^[0-9a-fA-F]{40,64}$")
  manifest_path: str = Field(default="mobius.json", min_length=1, max_length=512)
  public_identity: _PUBLIC_IDENTITY = "anonymous"
  contribution_id: str = Field(default="", max_length=200)


class RatingIn(BaseModel):
  value: int = Field(ge=1, le=5)
  revision_id: str = Field(min_length=8, max_length=200)


class CommentIn(BaseModel):
  body: str = Field(min_length=1, max_length=4000)
  public_identity: _PUBLIC_IDENTITY = "anonymous"


class ReportIn(BaseModel):
  reason: Literal[
    "spam", "harassment", "unsafe", "off_topic", "personal_information",
  ]


def _idempotency(value: str | None) -> str:
  key = str(value or "")
  if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{15,127}", key):
    raise HTTPException(400, "A valid Idempotency-Key is required.")
  return key


def _safe_public_id(value: str, label: str) -> str:
  if not _PUBLIC_ID.fullmatch(value):
    raise HTTPException(400, f"{label} is invalid.")
  return value


def _broker_error(exc: CommunityBrokerError) -> HTTPException:
  headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
  return HTTPException(
    status_code=exc.status_code,
    detail={"code": exc.code, "message": exc.detail},
    headers=headers,
  )


async def _request(*args, **kwargs) -> JSONResponse:
  try:
    payload, status, headers = await community_broker.request(*args, **kwargs)
  except CommunityBrokerError as exc:
    raise _broker_error(exc) from exc
  outgoing = {
    key.title(): value for key, value in headers.items()
    if key in {"etag", "last-modified", "retry-after"}
  }
  outgoing["Cache-Control"] = "no-store"
  return JSONResponse(payload, status_code=status, headers=outgoing)


@router.get("/identity")
async def community_identity(
  _: models.Owner = Depends(get_owner_or_app_with_manage_apps),
) -> JSONResponse:
  return await _request("GET", "/identity")


@router.get("/apps")
async def list_community_apps(
  q: str = Query(default="", max_length=160),
  review_status: str = Query(default="", max_length=40),
  limit: int = Query(default=50, ge=1, le=100),
  offset: int = Query(default=0, ge=0, le=10_000),
  _: models.Owner = Depends(get_owner_or_app_with_manage_apps),
) -> JSONResponse:
  return await _request(
    "GET", f"{COMMUNITY_PREFIX}/apps",
    params={"q": q, "review_status": review_status, "limit": limit, "offset": offset},
  )


@router.get("/apps/{app_id}")
async def get_community_app(
  app_id: str,
  _: models.Owner = Depends(get_owner_or_app_with_manage_apps),
) -> JSONResponse:
  return await _request(
    "GET", f"{COMMUNITY_PREFIX}/apps/{_safe_public_id(app_id, 'App id')}",
  )


@router.get("/apps/{app_id}/revisions/{revision_id}")
async def get_community_revision(
  app_id: str,
  revision_id: str,
  _: models.Owner = Depends(get_owner_or_app_with_manage_apps),
) -> JSONResponse:
  return await _request(
    "GET",
    f"{COMMUNITY_PREFIX}/apps/{_safe_public_id(app_id, 'App id')}"
    f"/revisions/{_safe_public_id(revision_id, 'Revision id')}",
  )


@router.post(
  "/publications",
  dependencies=[Depends(reject_cross_site)],
)
async def publish_local_app(
  body: PublishLocalAppIn,
  db: Session = Depends(get_db),
  _: models.Owner = Depends(get_owner_or_app_with_manage_apps),
  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
  app = (
    db.query(models.App)
    .filter(models.App.id == body.app_id, models.App.deleted_at.is_(None))
    .first()
  )
  if app is None:
    raise HTTPException(404, "App not found.")
  try:
    async with fs_locks.source_dir_lock(str(app.source_dir)):
      accepted_commit, files = await asyncio.to_thread(build_public_snapshot, app)
  except CommunityPublicationError as exc:
    raise HTTPException(
      exc.status_code, {"code": exc.code, "message": exc.detail},
    ) from exc
  payload = {
    "local_app_id": f"app:{app.id}:{app.slug}",
    "public_identity": body.public_identity,
    "files": files,
  }
  response = await _request(
    "POST", f"{COMMUNITY_PREFIX}/publications",
    body=payload,
    idempotency_key=_idempotency(idempotency_key),
  )
  response.headers["X-Mobius-Accepted-Source-Commit"] = accepted_commit
  return response


@router.post(
  "/apps",
  dependencies=[Depends(reject_cross_site)],
)
async def publish_existing_github_revision(
  body: ExistingGitHubRevisionIn,
  _: models.Owner = Depends(get_owner_or_app_with_manage_apps),
  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
  return await _request(
    "POST", f"{COMMUNITY_PREFIX}/apps",
    body={
      "github": {
        "repository": body.repository,
        "commit_sha": body.commit_sha.lower(),
        "manifest_path": body.manifest_path,
      },
      "public_identity": body.public_identity,
      "contribution_id": body.contribution_id,
    },
    idempotency_key=_idempotency(idempotency_key),
  )


@router.put(
  "/apps/{app_id}/rating",
  dependencies=[Depends(reject_cross_site)],
)
async def set_community_rating(
  app_id: str,
  body: RatingIn,
  _: models.Owner = Depends(get_owner_or_app_with_manage_apps),
  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
  return await _request(
    "PUT", f"{COMMUNITY_PREFIX}/apps/{_safe_public_id(app_id, 'App id')}/rating",
    body=body.model_dump(), idempotency_key=_idempotency(idempotency_key),
  )


@router.delete(
  "/apps/{app_id}/rating",
  dependencies=[Depends(reject_cross_site)],
)
async def remove_community_rating(
  app_id: str,
  _: models.Owner = Depends(get_owner_or_app_with_manage_apps),
  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
  return await _request(
    "DELETE", f"{COMMUNITY_PREFIX}/apps/{_safe_public_id(app_id, 'App id')}/rating",
    idempotency_key=_idempotency(idempotency_key),
  )


@router.post(
  "/apps/{app_id}/revisions/{revision_id}/comments",
  dependencies=[Depends(reject_cross_site)],
)
async def add_community_comment(
  app_id: str,
  revision_id: str,
  body: CommentIn,
  _: models.Owner = Depends(get_owner_or_app_with_manage_apps),
  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
  return await _request(
    "POST",
    f"{COMMUNITY_PREFIX}/apps/{_safe_public_id(app_id, 'App id')}"
    f"/revisions/{_safe_public_id(revision_id, 'Revision id')}/comments",
    body=body.model_dump(), idempotency_key=_idempotency(idempotency_key),
  )


@router.delete(
  "/comments/{comment_id}",
  dependencies=[Depends(reject_cross_site)],
)
async def withdraw_community_comment(
  comment_id: str,
  _: models.Owner = Depends(get_owner_or_app_with_manage_apps),
  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
  return await _request(
    "DELETE", f"{COMMUNITY_PREFIX}/comments/{_safe_public_id(comment_id, 'Comment id')}",
    idempotency_key=_idempotency(idempotency_key),
  )


@router.post(
  "/comments/{comment_id}/reports",
  dependencies=[Depends(reject_cross_site)],
)
async def report_community_comment(
  comment_id: str,
  body: ReportIn,
  _: models.Owner = Depends(get_owner_or_app_with_manage_apps),
  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
  return await _request(
    "POST",
    f"{COMMUNITY_PREFIX}/comments/{_safe_public_id(comment_id, 'Comment id')}/reports",
    body=body.model_dump(), idempotency_key=_idempotency(idempotency_key),
  )


@router.post(
  "/apps/{app_id}/revisions/{revision_id}/reviews",
  dependencies=[Depends(reject_cross_site)],
)
async def add_community_review(
  app_id: str,
  revision_id: str,
  body: dict[str, Any] = Body(...),
  _: models.Owner = Depends(get_owner_or_app_with_manage_apps),
  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
  if len(str(body)) > 100_000:
    raise HTTPException(413, "Review evidence is too large.")
  return await _request(
    "POST",
    f"{COMMUNITY_PREFIX}/apps/{_safe_public_id(app_id, 'App id')}"
    f"/revisions/{_safe_public_id(revision_id, 'Revision id')}/reviews",
    body=body, idempotency_key=_idempotency(idempotency_key),
  )
