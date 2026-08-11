from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import subprocess

import httpx
import pytest

from app.contribution_broker import (
  ContributionBrokerClient,
  ContributionBrokerError,
  bound_request_id,
  canonical_body,
)
from app.github_contribution_git import _reviewed_branch_diff
from app.routes import contribution_relay as relay_route


def _git(repo, *args, input_bytes=None):
  result = subprocess.run(
    ["git", "-C", str(repo), *args],
    input=input_bytes,
    capture_output=True,
    check=True,
  )
  return result.stdout.decode().strip()


def test_merged_snapshot_preserves_upstream_and_reviewed_changes(tmp_path, monkeypatch):
  repo = tmp_path / "review"
  repo.mkdir()
  _git(repo, "init", "-q")
  _git(repo, "config", "user.name", "Möbius")
  _git(repo, "config", "user.email", "mobius@example.test")
  (repo / "notes.txt").write_text("first\nmiddle\nlast\n")
  _git(repo, "add", "notes.txt")
  _git(repo, "commit", "-qm", "Base")
  base = _git(repo, "rev-parse", "HEAD")

  _git(repo, "checkout", "-qb", "feature")
  (repo / "notes.txt").write_text("reviewed\nmiddle\nlast\n")
  _git(repo, "add", "notes.txt")
  _git(
    repo,
    "commit",
    "-qm",
    "Reviewed change\n\nCo-authored-by: Möbius Agent <mobius-agent@users.noreply.github.com>",
  )
  head = _git(repo, "rev-parse", "HEAD")
  reviewed_diff = _reviewed_branch_diff(repo, base, head)
  diff_path = tmp_path / "review.diff"
  diff_path.write_bytes(reviewed_diff)

  _git(repo, "checkout", "-q", "-b", "upstream", base)
  (repo / "notes.txt").write_text("first\nmiddle\nupstream\n")
  _git(repo, "add", "notes.txt")
  _git(repo, "commit", "-qm", "Upstream change")
  upstream = _git(repo, "rev-parse", "HEAD")
  _git(repo, "checkout", "-q", "feature")

  monkeypatch.setattr(relay_route, "_safe_repo_path", lambda _raw: repo)
  monkeypatch.setattr(
    relay_route,
    "_assert_merges_with_upstream",
    lambda *_args: {
      "last_submit_upstream_branch": "main",
      "last_submit_upstream_sha": upstream,
    },
  )
  record = {
    "id": "review-1",
    "type": "pr",
    "repo": "mobius-os/mobius",
    "branch": "feature",
    "plan": {
      "action": "pr",
      "repo": "mobius-os/mobius",
      "repo_path": str(repo),
      "branch": "feature",
      "base_sha": base,
      "head_sha": head,
      "diff_sha256": hashlib.sha256(reviewed_diff).hexdigest(),
    },
  }

  merge, files = relay_route._merged_snapshot(record, diff_path)

  assert merge["base_sha"] == upstream
  assert len(files) == 1
  assert files[0]["path"] == "notes.txt"
  assert base64.b64decode(files[0]["content_base64"]) == (
    b"reviewed\nmiddle\nupstream\n"
  )
  assert _git(repo, "show", f"{merge['expected_tree_sha']}:notes.txt") == (
    "reviewed\nmiddle\nupstream"
  )


def test_contribution_broker_binds_body_request_id_and_disconnect_key():
  seen = []

  async def handler(request: httpx.Request):
    seen.append(request)
    if request.url.path.endswith("/github"):
      return httpx.Response(200, json={"connected": False})
    return httpx.Response(201, json={"id": "ctr_12345678"})

  client = ContributionBrokerClient(transport=httpx.MockTransport(handler))
  body = {"repo": "mobius-os/mobius", "files": []}
  key = "mobius-pr:1234567890abcdef"

  async def run():
    created = await client.request(
      "POST", "/v1/contributions", body=body, idempotency_key=key,
    )
    disconnected = await client.request(
      "DELETE", "/v1/contributions/github",
      idempotency_key="github-disconnect:12345678",
    )
    return created, disconnected

  created, disconnected = asyncio.run(run())
  assert created[0]["id"] == "ctr_12345678"
  assert disconnected[0] == {"connected": False}
  encoded = canonical_body(body)
  assert seen[0].headers["Idempotency-Key"] == key
  assert seen[0].headers["X-Mobius-Request-Id"] == bound_request_id(
    "POST", "/v1/contributions", encoded, key,
  )
  assert b"user_" not in seen[0].content


def test_contribution_broker_rejects_route_expansion_and_surfaces_quota():
  async def handler(_request: httpx.Request):
    return httpx.Response(
      429,
      headers={"Retry-After": "120"},
      json={"error": {"code": "quota", "message": "Daily limit reached."}},
    )

  client = ContributionBrokerClient(transport=httpx.MockTransport(handler))

  async def run():
    with pytest.raises(ValueError):
      await client.request("POST", "/v1/contributions/other", body={})
    with pytest.raises(ValueError):
      await client.request("GET", "/v1/contributions/ctr_12345678?subject=other")
    with pytest.raises(ContributionBrokerError) as caught:
      await client.request(
        "POST", "/v1/contributions", body={},
        idempotency_key="mobius-pr:1234567890abcdef",
      )
    return caught.value

  error = asyncio.run(run())
  assert error.status_code == 429
  assert error.code == "quota"
  assert error.retry_after == 120
  assert "Daily limit" in error.detail
