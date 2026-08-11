"""Owner-confirmed publication of reviewed changes through the Möbius bot."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import subprocess
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app import fs_locks
from app.contribution_broker import (
  CONTRIBUTION_PREFIX,
  ContributionBrokerError,
  contribution_broker,
)
from app.contribution_records import (
  now_iso,
  read_record,
  record_paths,
  write_record,
)
from app.database import get_db
from app.deps import Principal, get_principal, reject_cross_site
from app.github_contribution_git import (
  _assert_clean_worktree,
  _assert_coauthor_trailer,
  _assert_fresh,
  _assert_merges_with_upstream,
  _git_env,
  _validate_branch,
  _validate_repo_slug,
)
from app.github_contributions import (
  ContributionSubmitError,
  _claim_record,
  _mark_submit_failure,
  _recheck_submit_app,
  _safe_repo_path,
  _validate_submit_app,
)


router = APIRouter(prefix="/api/contribution-relay", tags=["contribution-relay"])
_limiter = Limiter(key_func=get_remote_address)
_SHA = re.compile(r"^[0-9a-f]{40}$")


class RelaySubmitIn(BaseModel):
  confirm_publication: Literal[True]
  public_identity: Literal["anonymous", "github"] = "anonymous"
  submitter: Literal["contribute-button", "chat-review-card"] = (
    "contribute-button"
  )


class DisconnectGithubIn(BaseModel):
  confirm_disconnect: Literal[True]


def _run_git_bytes(repo: Path, *args: str) -> bytes:
  result = subprocess.run(
    ["git", "-C", str(repo), *args],
    cwd=str(repo),
    env=_git_env(repo),
    capture_output=True,
    text=False,
    timeout=60,
    check=False,
  )
  if result.returncode:
    detail = (result.stderr or result.stdout or b"Git command failed.")[:600]
    raise ContributionSubmitError(
      detail.decode("utf-8", errors="replace").strip()
    )
  return result.stdout


def _tree_entry(repo: Path, tree: str, path: str) -> tuple[str, str]:
  raw = _run_git_bytes(repo, "ls-tree", "-z", tree, "--", path)
  entries = [item for item in raw.split(b"\0") if item]
  if len(entries) != 1 or b"\t" not in entries[0]:
    raise ContributionSubmitError(
      "The reviewed merge tree contains an unsupported file entry."
    )
  metadata, raw_path = entries[0].split(b"\t", 1)
  parts = metadata.split()
  if len(parts) != 3 or parts[1] != b"blob":
    raise ContributionSubmitError(
      "Only regular files can be submitted through the Möbius bot."
    )
  try:
    resolved_path = raw_path.decode("utf-8")
  except UnicodeDecodeError as exc:
    raise ContributionSubmitError(
      "File names must be valid UTF-8 before this contribution can be sent."
    ) from exc
  if resolved_path != path:
    raise ContributionSubmitError("The reviewed file path could not be verified.")
  mode = parts[0].decode("ascii")
  if mode not in {"100644", "100755"}:
    raise ContributionSubmitError(
      "Symlinks and special files cannot be submitted through the Möbius bot."
    )
  return mode, parts[2].decode("ascii")


def _merged_snapshot(record: dict, diff_path: Path) -> tuple[dict, list[dict]]:
  plan = record.get("plan") if isinstance(record.get("plan"), dict) else {}
  repo = _safe_repo_path(plan.get("repo_path"))
  repo_slug = _validate_repo_slug(plan.get("repo") or record.get("repo"))
  branch = _validate_branch(plan.get("branch") or record.get("branch"))
  _assert_clean_worktree(repo)
  _base_sha, head_sha, _diff_hash = _assert_fresh(
    record, diff_path, repo, branch,
  )
  _assert_coauthor_trailer(repo, branch)
  upstream = _assert_merges_with_upstream(repo, repo_slug, branch)
  upstream_sha = str(upstream.get("last_submit_upstream_sha") or "")
  base_ref = str(upstream.get("last_submit_upstream_branch") or "")
  if not _SHA.fullmatch(upstream_sha) or not base_ref:
    raise ContributionSubmitError(
      "The current upstream branch could not be verified."
    )
  merged = _run_git_bytes(
    repo, "merge-tree", "--write-tree", upstream_sha, head_sha,
  ).decode("ascii", errors="strict").splitlines()
  expected_tree_sha = merged[0].strip() if merged else ""
  if not _SHA.fullmatch(expected_tree_sha):
    raise ContributionSubmitError(
      "The exact reviewed merge tree could not be constructed."
    )
  raw_changes = _run_git_bytes(
    repo,
    "diff",
    "--name-status",
    "-z",
    "--no-renames",
    upstream_sha,
    expected_tree_sha,
  )
  tokens = raw_changes.split(b"\0")
  if tokens and tokens[-1] == b"":
    tokens.pop()
  if len(tokens) % 2 or len(tokens) > 160:
    raise ContributionSubmitError(
      "This contribution has too many or unsupported file changes."
    )
  files = []
  for index in range(0, len(tokens), 2):
    status = tokens[index].decode("ascii", errors="strict")
    try:
      path = tokens[index + 1].decode("utf-8")
    except UnicodeDecodeError as exc:
      raise ContributionSubmitError(
        "File names must be valid UTF-8 before this contribution can be sent."
      ) from exc
    if status not in {"A", "M", "D"}:
      raise ContributionSubmitError(
        "Renames and special Git changes must be reviewed as ordinary files."
      )
    source_tree = upstream_sha if status == "D" else expected_tree_sha
    mode, _blob_sha = _tree_entry(repo, source_tree, path)
    content = b"" if status == "D" else _run_git_bytes(
      repo, "show", f"{expected_tree_sha}:{path}",
    )
    files.append({
      "path": path,
      "operation": {"A": "add", "M": "modify", "D": "delete"}[status],
      "mode": mode,
      "content_base64": base64.b64encode(content).decode("ascii") if content else "",
    })
  if not files:
    raise ContributionSubmitError("This contribution no longer changes any files.")
  return {
    "repo": repo_slug,
    "base_ref": base_ref,
    "base_sha": upstream_sha,
    "expected_tree_sha": expected_tree_sha,
    **upstream,
  }, files


def _idempotency_key(app_id: int, record_id: str, record: dict) -> str:
  plan = record.get("plan") if isinstance(record.get("plan"), dict) else {}
  material = "\0".join((
    str(app_id), record_id, str(plan.get("base_sha") or ""),
    str(plan.get("head_sha") or ""), str(plan.get("diff_sha256") or ""),
  )).encode()
  return "mobius-pr:" + hashlib.sha256(material).hexdigest()


def _relay_failure(
  *, app_id: int, record_path: Path, exc: ContributionBrokerError,
) -> dict | None:
  current = read_record(record_path)
  retryable = exc.status_code in {502, 503, 504} or exc.code in {
    "submission_in_progress", "github_error", "relay_unavailable",
  }
  if retryable and current.get("status") == "submitting":
    next_record = {
      **current,
      "last_submit_error": exc.detail,
      "last_submit_error_code": exc.code,
      "updated_at": now_iso(),
    }
    write_record(record_path, next_record)
    return next_record
  return _mark_submit_failure(
    app_id=app_id,
    record_path=record_path,
    message=exc.detail,
    detail=exc.code,
  )


@router.post(
  "/{app_id}/{record_id}/submit",
  dependencies=[Depends(reject_cross_site)],
)
@_limiter.limit("5/minute")
async def submit_through_mobius(
  request: Request,
  app_id: int,
  record_id: str,
  body: RelaySubmitIn,
  db: Session = Depends(get_db),
  principal: Principal = Depends(get_principal),
):
  expected_nonce = _validate_submit_app(app_id, principal, db)
  async with fs_locks.app_storage_lock(app_id):
    _recheck_submit_app(db, app_id, expected_nonce)
    record_path, diff_path = record_paths(app_id, record_id)
    current = read_record(record_path)
    if (
      current.get("status") == "submitting"
      and current.get("submission_mode") == "mobius-bot"
      and current.get("relay_idempotency_key")
    ):
      claimed = current
    else:
      claimed, record_path, diff_path = _claim_record(
        app_id=app_id,
        record_id=record_id,
        db=db,
        expected_nonce=expected_nonce,
        submitter=body.submitter,
      )
      claimed = {
        **claimed,
        "submission_mode": "mobius-bot",
        "public_identity": body.public_identity,
        "relay_idempotency_key": _idempotency_key(
          app_id, record_id, claimed,
        ),
      }
      write_record(record_path, claimed)
  db.close()

  try:
    async with fs_locks.source_dir_lock(
      str(_safe_repo_path((claimed.get("plan") or {}).get("repo_path")))
    ):
      merge, files = await asyncio.to_thread(
        _merged_snapshot, claimed, diff_path,
      )
    title = str(claimed.get("title") or "Reviewed Möbius contribution").strip()
    description = str(
      claimed.get("description") or claimed.get("summary") or "Reviewed in Möbius."
    ).strip()
    payload = {
      "repo": merge["repo"],
      "base_ref": merge["base_ref"],
      "base_sha": merge["base_sha"],
      "expected_tree_sha": merge["expected_tree_sha"],
      "title": title[:256],
      "body": description[:65_536],
      "commit_message": title[:512],
      "local_record_id": record_id,
      "public_identity": str(claimed.get("public_identity") or "anonymous"),
      "draft": True,
      "files": files,
    }
    result, _status, _headers = await contribution_broker.request(
      "POST",
      CONTRIBUTION_PREFIX,
      body=payload,
      idempotency_key=str(claimed["relay_idempotency_key"]),
    )
  except ContributionSubmitError as exc:
    async with fs_locks.app_storage_lock(app_id):
      _recheck_submit_app(db, app_id, expected_nonce)
      record = _mark_submit_failure(
        app_id=app_id,
        record_path=record_path,
        message=exc.message,
        record_patch=exc.record_patch,
        detail=exc.detail,
      )
    raise HTTPException(
      exc.status_code,
      {"code": exc.code or "review_changed", "message": exc.message, "record": record},
    ) from exc
  except ContributionBrokerError as exc:
    async with fs_locks.app_storage_lock(app_id):
      _recheck_submit_app(db, app_id, expected_nonce)
      record = _relay_failure(app_id=app_id, record_path=record_path, exc=exc)
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    raise HTTPException(
      exc.status_code,
      {"code": exc.code, "message": exc.detail, "record": record},
      headers=headers,
    ) from exc

  pr = result.get("pr") if isinstance(result, dict) else None
  contribution_id = str(result.get("id") or "") if isinstance(result, dict) else ""
  if (
    not contribution_id
    or not isinstance(pr, dict)
    or not str(pr.get("url") or "").startswith("https://github.com/")
  ):
    invalid = ContributionBrokerError(
      502,
      "The contribution relay returned an invalid result. Retry will reconcile the same request.",
      "invalid_relay_response",
    )
    async with fs_locks.app_storage_lock(app_id):
      _recheck_submit_app(db, app_id, expected_nonce)
      record = _relay_failure(app_id=app_id, record_path=record_path, exc=invalid)
    raise HTTPException(
      502,
      {"code": invalid.code, "message": invalid.detail, "record": record},
    )
  async with fs_locks.app_storage_lock(app_id):
    _recheck_submit_app(db, app_id, expected_nonce)
    current = read_record(record_path)
    if current.get("status") != "submitting":
      raise HTTPException(409, "This contribution changed while it was sent.")
    submitted = {
      **current,
      "status": str(result.get("status") or "draft"),
      "url": pr["url"],
      "number": pr.get("number"),
      "relay_contribution_id": contribution_id,
      "relay_branch": pr.get("branch"),
      "relay_head_sha": pr.get("head_sha"),
      "last_submit_upstream_branch": merge["base_ref"],
      "last_submit_upstream_sha": merge["base_sha"],
      "submitted_at": now_iso(),
      "updated_at": now_iso(),
    }
    submitted.pop("last_submit_error", None)
    submitted.pop("last_submit_error_code", None)
    write_record(record_path, submitted)
  return {"record": submitted, "contribution": result}


@router.get("/{app_id}/github")
@_limiter.limit("20/minute")
async def relay_github_status(
  request: Request,
  app_id: int,
  db: Session = Depends(get_db),
  principal: Principal = Depends(get_principal),
):
  _validate_submit_app(app_id, principal, db)
  try:
    payload, _status, _headers = await contribution_broker.request(
      "GET", CONTRIBUTION_PREFIX + "/github/status",
    )
    return payload
  except ContributionBrokerError as exc:
    raise HTTPException(
      exc.status_code, {"code": exc.code, "message": exc.detail}
    ) from exc


@router.delete(
  "/{app_id}/github",
  dependencies=[Depends(reject_cross_site)],
)
@_limiter.limit("5/minute")
async def disconnect_relay_github(
  request: Request,
  app_id: int,
  body: DisconnectGithubIn,
  db: Session = Depends(get_db),
  principal: Principal = Depends(get_principal),
):
  _validate_submit_app(app_id, principal, db)
  key = "github-disconnect:" + hashlib.sha256(str(app_id).encode()).hexdigest()
  try:
    payload, _status, _headers = await contribution_broker.request(
      "DELETE",
      CONTRIBUTION_PREFIX + "/github",
      idempotency_key=key,
    )
    return payload
  except ContributionBrokerError as exc:
    raise HTTPException(
      exc.status_code, {"code": exc.code, "message": exc.detail}
    ) from exc


@router.get("/{app_id}/{record_id}/status")
@_limiter.limit("30/minute")
async def relay_contribution_status(
  request: Request,
  app_id: int,
  record_id: str,
  db: Session = Depends(get_db),
  principal: Principal = Depends(get_principal),
):
  expected_nonce = _validate_submit_app(app_id, principal, db)
  record_path, _diff_path = record_paths(app_id, record_id)
  record = read_record(record_path)
  contribution_id = str(record.get("relay_contribution_id") or "")
  if not contribution_id:
    raise HTTPException(404, "This contribution has not reached the relay yet.")
  try:
    payload, _status, _headers = await contribution_broker.request(
      "GET", CONTRIBUTION_PREFIX + "/" + contribution_id,
    )
  except ContributionBrokerError as exc:
    raise HTTPException(
      exc.status_code, {"code": exc.code, "message": exc.detail}
    ) from exc
  async with fs_locks.app_storage_lock(app_id):
    _recheck_submit_app(db, app_id, expected_nonce)
    current = read_record(record_path)
    current = {
      **current,
      "status": str(payload.get("status") or current.get("status") or "draft"),
      "updated_at": now_iso(),
    }
    write_record(record_path, current)
  return {"record": current, "contribution": payload}
