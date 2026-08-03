"""Fail-closed helpers for recurring immutable managed-core releases.

The controller's authenticated ``/internal/core-releases/current`` endpoint is
the source of truth for the dynamic core prerequisite.  Repository variables
or manual inputs express release intent; this module requires those values to
match the completed controller identity exactly before a workflow can build or
bind its successor.

The frozen ``:external-recovery`` compatibility channel is deliberately not a
dynamic release pointer.  Its separate A' inventory remains owned by
``external_recovery_release.py``.  This module only inspects digest references
and writes controller payload files; it has no registry-write operation.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from external_recovery_release import (
  CutoverIdentity,
  DIGEST_RE,
  EPOCH_RE,
  GIT_SHA_RE,
  ImageIdentity,
  ReleaseError,
  inspect_digest,
  validate_cutover_identity,
)


@dataclass(frozen=True)
class CurrentCoreIdentity:
  generation: int
  build_sha: str
  image_digest: str
  release_channel: str
  platform_release_ref: str


@dataclass(frozen=True)
class CurrentDecision:
  decision: str
  current: CurrentCoreIdentity
  active_image_digest: str = ""


ACTIVE_STATUSES = {
  "aborting",
  "auditing",
  "awaiting_redeploy",
  "finalizing",
  "publish_authorized",
  "redeploy_failed",
  "redeploying",
  "repair_required",
  "rolling_back",
}
ACTIVE_FIELDS = (
  "cutover_status",
  "active_epoch",
  "active_build_sha",
  "active_image_digest",
)


def _string(body: Mapping[str, Any], field: str) -> str:
  value = body.get(field, "")
  if not isinstance(value, str):
    raise ReleaseError(f"controller field {field} is not a string")
  return value.strip().lower()


def _load_json(path: str) -> Mapping[str, Any]:
  try:
    with Path(path).open(encoding="utf-8") as source:
      value = json.load(source)
  except (OSError, ValueError) as exc:
    raise ReleaseError("controller returned invalid JSON") from exc
  if not isinstance(value, dict):
    raise ReleaseError("controller response is not an object")
  return value


def classify_current_response(
  body: Mapping[str, Any],
  http_status: int,
  *,
  prerequisite: ImageIdentity,
  candidate_sha: str,
  candidate_epoch: str,
  branch_head_sha: str,
  release_channel: str,
  platform_release_ref: str,
) -> CurrentDecision:
  """Require release intent to equal the controller's completed core."""

  if not GIT_SHA_RE.fullmatch(candidate_sha):
    raise ReleaseError("invalid candidate build SHA")
  if not GIT_SHA_RE.fullmatch(branch_head_sha):
    raise ReleaseError("invalid protected branch head SHA")
  if (
    not EPOCH_RE.fullmatch(candidate_epoch)
    or candidate_epoch != f"managed-core-v1-{candidate_sha}"
  ):
    raise ReleaseError("candidate epoch is not deterministic")
  if not GIT_SHA_RE.fullmatch(prerequisite.revision):
    raise ReleaseError("invalid prerequisite build SHA")
  if not DIGEST_RE.fullmatch(prerequisite.digest):
    raise ReleaseError("invalid prerequisite image digest")
  if http_status != 200:
    error = _string(body, "error") or _string(body, "status") or "unknown_error"
    raise ReleaseError(
      f"controller current-core lookup returned HTTP {http_status} ({error})"
    )
  status = _string(body, "status")

  generation = body.get("generation")
  if (
    isinstance(generation, bool)
    or not isinstance(generation, int)
    or generation <= 0
  ):
    raise ReleaseError("controller omitted the completed core generation")
  current = CurrentCoreIdentity(
    generation=generation,
    build_sha=_string(body, "build_sha"),
    image_digest=_string(body, "image_digest"),
    release_channel=_string(body, "release_channel"),
    platform_release_ref=_string(body, "platform_release_ref"),
  )
  if not GIT_SHA_RE.fullmatch(current.build_sha):
    raise ReleaseError("controller returned an invalid current build SHA")
  if not DIGEST_RE.fullmatch(current.image_digest):
    raise ReleaseError("controller returned an invalid current image digest")
  if current.release_channel != release_channel.lower():
    raise ReleaseError("controller current core changed release_channel")
  if current.platform_release_ref != platform_release_ref.lower():
    raise ReleaseError("controller current core changed platform_release_ref")
  if (
    current.build_sha != prerequisite.revision
    or current.image_digest != prerequisite.digest
  ):
    raise ReleaseError(
      "protected release prerequisite does not match the completed controller core"
    )
  if status == "completed":
    if any(body.get(field) not in (None, "") for field in ACTIVE_FIELDS):
      raise ReleaseError("completed controller core unexpectedly has an active tuple")
    if candidate_sha == current.build_sha:
      return CurrentDecision("replay", current)
    if candidate_sha != branch_head_sha:
      raise ReleaseError("a fresh release candidate must be protected branch HEAD")
    return CurrentDecision("release", current)

  if status not in {"active", "awaiting_replacement"}:
    raise ReleaseError(f"controller returned unsupported current-core status {status!r}")

  cutover_status = _string(body, "cutover_status")
  active_epoch = _string(body, "active_epoch")
  active_build_sha = _string(body, "active_build_sha")
  active_image_digest = _string(body, "active_image_digest")
  if not EPOCH_RE.fullmatch(active_epoch):
    raise ReleaseError("controller returned an invalid active epoch")
  if not GIT_SHA_RE.fullmatch(active_build_sha):
    raise ReleaseError("controller returned an invalid active build SHA")
  if active_image_digest and not DIGEST_RE.fullmatch(active_image_digest):
    raise ReleaseError("controller returned an invalid active image digest")
  if active_image_digest == current.image_digest:
    raise ReleaseError("controller active digest equals its prerequisite")

  if status == "active":
    if cutover_status not in ACTIVE_STATUSES:
      raise ReleaseError("controller returned an unsupported active cutover status")
    if active_build_sha != candidate_sha or active_epoch != candidate_epoch:
      raise ReleaseError("candidate does not match the exact active controller tuple")
    if candidate_sha != branch_head_sha and not active_image_digest:
      raise ReleaseError(
        "an unbound active candidate must remain protected branch HEAD"
      )
    return CurrentDecision("resume", current, active_image_digest)

  if status == "awaiting_replacement":
    if cutover_status != "awaiting_replacement":
      raise ReleaseError("controller replacement status is inconsistent")
    if candidate_sha != branch_head_sha:
      raise ReleaseError("a replacement candidate must be protected branch HEAD")
    if candidate_sha in {current.build_sha, active_build_sha}:
      raise ReleaseError("replacement candidate must supersede the failed candidate")
    return CurrentDecision("replacement", current)

  raise AssertionError("unreachable current-core status")


def assert_exact_image(repository: str, expected: ImageIdentity) -> None:
  observed = inspect_digest(repository, expected.digest)
  if observed != expected:
    raise ReleaseError("immutable core image does not match its expected revision")


def write_payload(path: str, identity: CutoverIdentity) -> None:
  validate_cutover_identity(
    identity, require_removal_digest=bool(identity.removal_image_digest)
  )
  body = {
    "epoch": identity.epoch,
    "release_channel": identity.release_channel,
    "platform_release_ref": identity.platform_release_ref,
    "prerequisite_build_sha": identity.prerequisite_build_sha,
    "prerequisite_image_digest": identity.prerequisite_image_digest,
    "removal_build_sha": identity.removal_build_sha,
  }
  if identity.removal_image_digest:
    body["removal_image_digest"] = identity.removal_image_digest
  try:
    Path(path).write_text(
      json.dumps(body, separators=(",", ":"), sort_keys=True),
      encoding="utf-8",
    )
  except OSError as exc:
    raise ReleaseError("could not write the controller payload") from exc


def _add_identity_args(parser: argparse.ArgumentParser, *, digest: bool) -> None:
  parser.add_argument("--epoch", required=True)
  parser.add_argument("--release-channel", required=True)
  parser.add_argument("--platform-release-ref", required=True)
  parser.add_argument("--prerequisite-sha", required=True)
  parser.add_argument("--prerequisite-digest", required=True)
  parser.add_argument("--candidate-sha", required=True)
  if digest:
    parser.add_argument("--candidate-digest", required=True)


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser()
  commands = parser.add_subparsers(dest="command", required=True)

  current = commands.add_parser("current")
  current.add_argument("--response", required=True)
  current.add_argument("--http-status", required=True, type=int)
  current.add_argument("--release-channel", required=True)
  current.add_argument("--platform-release-ref", required=True)
  current.add_argument("--prerequisite-sha", required=True)
  current.add_argument("--prerequisite-digest", required=True)
  current.add_argument("--candidate-sha", required=True)
  current.add_argument("--candidate-epoch", required=True)
  current.add_argument("--branch-head-sha", required=True)

  image = commands.add_parser("image")
  image.add_argument("--repository", required=True)
  image.add_argument("--digest", required=True)
  image.add_argument("--revision", required=True)

  payload = commands.add_parser("payload")
  payload.add_argument("--output", required=True)
  _add_identity_args(payload, digest=False)

  bound_payload = commands.add_parser("bound-payload")
  bound_payload.add_argument("--output", required=True)
  _add_identity_args(bound_payload, digest=True)
  return parser


def _identity_from_args(args: argparse.Namespace, *, bound: bool) -> CutoverIdentity:
  return CutoverIdentity(
    epoch=args.epoch,
    release_channel=args.release_channel,
    platform_release_ref=args.platform_release_ref,
    prerequisite_build_sha=args.prerequisite_sha,
    prerequisite_image_digest=args.prerequisite_digest,
    removal_build_sha=args.candidate_sha,
    removal_image_digest=args.candidate_digest if bound else "",
  )


def main(argv: list[str] | None = None) -> int:
  args = build_parser().parse_args(argv)
  if args.command == "current":
    decision = classify_current_response(
      _load_json(args.response),
      args.http_status,
      prerequisite=ImageIdentity(
        digest=args.prerequisite_digest, revision=args.prerequisite_sha
      ),
      candidate_sha=args.candidate_sha,
      candidate_epoch=args.candidate_epoch,
      branch_head_sha=args.branch_head_sha,
      release_channel=args.release_channel,
      platform_release_ref=args.platform_release_ref,
    )
    print(
      f"{decision.decision}|{decision.current.generation}|"
      f"{decision.active_image_digest}"
    )
    return 0
  if args.command == "image":
    assert_exact_image(
      args.repository, ImageIdentity(args.digest, args.revision)
    )
    return 0
  if args.command == "payload":
    write_payload(args.output, _identity_from_args(args, bound=False))
    return 0
  write_payload(args.output, _identity_from_args(args, bound=True))
  return 0


if __name__ == "__main__":
  try:
    raise SystemExit(main())
  except ReleaseError as exc:
    print(f"managed core release refused: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc
