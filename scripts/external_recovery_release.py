"""Fail-closed helpers for the protected external-recovery image channel.

The controller contract deliberately exposes two recovery identities on every
successful core-release response. ``recovery_*`` is the generation's frozen
audit identity. ``current_recovery_*`` and the identical ``approved_recovery_*``
aliases are an atomic read of the durable current release. Active cutovers
require all three identities to agree; completed normal releases may observe a
newer current release, which is the one the workflow verifies at public
``mobius-recovery:stable``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
BUILD_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
EPOCH_RE = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
ABSENT_RE = re.compile(
  r"(?:not found|manifest unknown|name_unknown|manifest_unknown)", re.IGNORECASE
)


class ReleaseError(RuntimeError):
  """The controller or registry is outside an explicitly permitted state."""


@dataclass(frozen=True)
class ImageIdentity:
  digest: str
  revision: str


@dataclass(frozen=True)
class CutoverIdentity:
  epoch: str
  release_channel: str
  platform_release_ref: str
  prerequisite_build_sha: str
  prerequisite_image_digest: str
  removal_build_sha: str
  removal_image_digest: str = ""


@dataclass(frozen=True)
class RecoveryIdentity:
  sequence: int
  build_sha: str
  image_digest: str


@dataclass(frozen=True)
class GateDecision:
  decision: str
  bound_digest: str
  frozen_recovery: RecoveryIdentity
  current_recovery: RecoveryIdentity


def validate_image_identity(identity: ImageIdentity) -> ImageIdentity:
  if not DIGEST_RE.fullmatch(identity.digest):
    raise ReleaseError("registry returned an invalid image digest")
  if not BUILD_SHA_RE.fullmatch(identity.revision):
    raise ReleaseError("registry returned an invalid image revision")
  return identity


def validate_cutover_identity(
  identity: CutoverIdentity, *, require_removal_digest: bool = False
) -> CutoverIdentity:
  if not EPOCH_RE.fullmatch(identity.epoch):
    raise ReleaseError("invalid cutover epoch")
  if not identity.release_channel:
    raise ReleaseError("release channel is required")
  if not identity.platform_release_ref.startswith("refs/heads/"):
    raise ReleaseError("platform release ref must be a full branch ref")
  if not GIT_SHA_RE.fullmatch(identity.prerequisite_build_sha):
    raise ReleaseError("invalid prerequisite build SHA")
  if not GIT_SHA_RE.fullmatch(identity.removal_build_sha):
    raise ReleaseError("invalid removal build SHA")
  if identity.prerequisite_build_sha == identity.removal_build_sha:
    raise ReleaseError("prerequisite and removal SHAs must differ")
  if not DIGEST_RE.fullmatch(identity.prerequisite_image_digest):
    raise ReleaseError("invalid prerequisite image digest")
  if require_removal_digest:
    if not DIGEST_RE.fullmatch(identity.removal_image_digest):
      raise ReleaseError("invalid removal image digest")
    if identity.prerequisite_image_digest == identity.removal_image_digest:
      raise ReleaseError("prerequisite and removal digests must differ")
  return identity


def _parse_image_identity(value: str) -> ImageIdentity:
  fields = value.strip().split("|", 1)
  if len(fields) != 2:
    raise ReleaseError("registry returned malformed image identity")
  return validate_image_identity(ImageIdentity(fields[0], fields[1]))


def inspect_tag(
  repository: str,
  tag: str,
  *,
  attempts: int = 5,
  runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
  sleeper: Callable[[float], None] = time.sleep,
) -> ImageIdentity | None:
  """Return a public tag identity; return ``None`` only after repeated 404s."""

  reference = f"{repository}:{tag}"
  command = [
    "docker",
    "buildx",
    "imagetools",
    "inspect",
    reference,
    "--format",
    '{{.Manifest.Digest}}|{{index .Image.Config.Labels "org.opencontainers.image.revision"}}',
  ]
  for attempt in range(1, attempts + 1):
    result = runner(
      command,
      capture_output=True,
      text=True,
      check=False,
      env=os.environ.copy(),
    )
    if result.returncode == 0:
      return _parse_image_identity(result.stdout)
    error = (result.stderr or "").strip()
    if reference.lower() not in error.lower() or not ABSENT_RE.search(error):
      raise ReleaseError(
        f"ambiguous registry failure for {reference}: {error or 'no error'}"
      )
    if attempt < attempts:
      sleeper(float(attempt))
  return None


def assert_frozen_legacy(
  *, main: ImageIdentity | None, daily: ImageIdentity | None, prerequisite: ImageIdentity
) -> None:
  validate_image_identity(prerequisite)
  if main != prerequisite:
    raise ReleaseError("public :main is not the configured compatibility floor")
  if daily is not None:
    raise ReleaseError("the frozen, previously absent :daily tag now exists")


def inventory_channels(
  repository: str, prerequisite: ImageIdentity
) -> ImageIdentity:
  main = inspect_tag(repository, "main")
  daily = inspect_tag(repository, "daily")
  target = inspect_tag(repository, "external-recovery")
  assert_frozen_legacy(main=main, daily=daily, prerequisite=prerequisite)
  if target is None:
    raise ReleaseError("the bootstrapped :external-recovery channel is absent")
  return validate_image_identity(target)


def assert_prewrite_channels(
  repository: str, prerequisite: ImageIdentity, initial_target: ImageIdentity
) -> None:
  target = inventory_channels(repository, prerequisite)
  if target != initial_target:
    raise ReleaseError(":external-recovery changed after the initial inventory")


def assert_final_channels(
  repository: str, prerequisite: ImageIdentity, released: ImageIdentity
) -> None:
  target = inventory_channels(repository, prerequisite)
  if target != released:
    raise ReleaseError(":external-recovery does not hold the selected release")


def assert_worker_release(
  repository: str, expected: ImageIdentity
) -> None:
  stable = inspect_tag(repository, "stable")
  if stable != validate_image_identity(expected):
    raise ReleaseError(
      "public mobius-recovery:stable does not match the controller's approved release"
    )


def _string(body: Mapping[str, Any], field: str) -> str:
  value = body.get(field, "")
  if not isinstance(value, str):
    raise ReleaseError(f"controller field {field} is not a string")
  return value.strip().lower()


def _recovery_identity(
  body: Mapping[str, Any], prefix: str = ""
) -> RecoveryIdentity:
  sequence = body.get(f"{prefix}recovery_release_sequence")
  build_sha = _string(body, f"{prefix}recovery_build_sha")
  image_digest = _string(body, f"{prefix}recovery_image_digest")
  if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
    raise ReleaseError(f"controller omitted the {prefix}recovery release sequence")
  if not BUILD_SHA_RE.fullmatch(build_sha):
    raise ReleaseError(f"controller omitted the {prefix}recovery build SHA")
  if not DIGEST_RE.fullmatch(image_digest):
    raise ReleaseError(f"controller omitted the {prefix}recovery image digest")
  return RecoveryIdentity(sequence, build_sha, image_digest)


def _response_recoveries(
  body: Mapping[str, Any], *, require_frozen_current_match: bool
) -> tuple[RecoveryIdentity, RecoveryIdentity]:
  frozen = _recovery_identity(body)
  current = _recovery_identity(body, "current_")
  approved = _recovery_identity(body, "approved_")
  if approved != current:
    raise ReleaseError("controller current and approved recovery aliases disagree")
  if require_frozen_current_match and frozen != current:
    raise ReleaseError("active cutover recovery identity is no longer frozen")
  return frozen, current


def _assert_common_response(
  body: Mapping[str, Any], expected: CutoverIdentity, *, completed: bool
) -> None:
  fields = (
    "release_channel",
    "platform_release_ref",
    "prerequisite_build_sha",
    "prerequisite_image_digest",
  )
  for field in fields:
    if _string(body, field) != getattr(expected, field):
      raise ReleaseError(f"controller response changed {field}")
  if completed:
    completed_sha = _string(body, "removal_build_sha")
    completed_digest = _string(body, "removal_image_digest")
    if not GIT_SHA_RE.fullmatch(completed_sha) or not DIGEST_RE.fullmatch(
      completed_digest
    ):
      raise ReleaseError("completed cutover has no exact removal identity")
    return
  if _string(body, "epoch") != expected.epoch:
    raise ReleaseError("controller response changed epoch")
  if _string(body, "removal_build_sha") != expected.removal_build_sha:
    raise ReleaseError("controller response changed removal_build_sha")


def classify_gate_response(
  body: Mapping[str, Any], http_status: int, expected: CutoverIdentity
) -> GateDecision:
  validate_cutover_identity(expected)
  status = _string(body, "status")
  if http_status not in {200, 202}:
    error = _string(body, "error") or status or "unknown_error"
    raise ReleaseError(f"controller prepublish returned HTTP {http_status} ({error})")
  if status == "cutover_already_complete":
    _assert_common_response(body, expected, completed=True)
    frozen, current = _response_recoveries(
      body, require_frozen_current_match=False
    )
    completed_sha = _string(body, "removal_build_sha")
    completed_digest = _string(body, "removal_image_digest")
    decision = (
      "completed_replay"
      if completed_sha == expected.removal_build_sha
      else "normal_release"
    )
    return GateDecision(decision, completed_digest, frozen, current)

  _assert_common_response(body, expected, completed=False)
  frozen, current = _response_recoveries(
    body, require_frozen_current_match=True
  )
  bound_digest = _string(body, "removal_image_digest")
  if status == "awaiting_redeploy":
    job_status = _string(body, "job_status")
    failed = body.get("failed")
    completed = body.get("completed")
    total = body.get("total")
    counts_are_ints = all(
      isinstance(value, int) and not isinstance(value, bool)
      for value in (failed, completed, total)
    )
    if (
      job_status == "completed"
      and counts_are_ints
      and failed == 0
      and completed == total
    ):
      return GateDecision("build_cutover", "", frozen, current)
    return GateDecision("wait", "", frozen, current)

  if status in {"publish_authorized", "redeploying", "finalizing", "redeploy_failed"}:
    if not DIGEST_RE.fullmatch(bound_digest):
      raise ReleaseError("active cutover has no exact bound removal digest")
    return GateDecision("resume_cutover", bound_digest, frozen, current)

  if status in {"auditing", "aborting", "repair_required", "rolling_back"}:
    return GateDecision("wait", bound_digest, frozen, current)
  raise ReleaseError(f"controller returned unsupported prepublish status {status!r}")


def assert_bind_response(
  body: Mapping[str, Any], http_status: int, expected: CutoverIdentity
) -> None:
  validate_cutover_identity(expected, require_removal_digest=True)
  if http_status != 200:
    error = _string(body, "error") or _string(body, "status") or "unknown_error"
    raise ReleaseError(f"controller bind returned HTTP {http_status} ({error})")
  _assert_common_response(body, expected, completed=False)
  if _string(body, "removal_image_digest") != expected.removal_image_digest:
    raise ReleaseError("controller bind changed removal_image_digest")
  if _string(body, "status") != "publish_authorized":
    raise ReleaseError("controller did not retain publish_authorized")
  if body.get("publish_permitted") is not True:
    raise ReleaseError("controller did not permit publication")
  _response_recoveries(body, require_frozen_current_match=True)


def classify_postpublish_response(
  body: Mapping[str, Any], http_status: int, expected: CutoverIdentity
) -> str:
  validate_cutover_identity(expected, require_removal_digest=True)
  status = _string(body, "status")
  if http_status not in {200, 202}:
    error = _string(body, "error") or status or "unknown_error"
    raise ReleaseError(f"controller postpublish returned HTTP {http_status} ({error})")
  completed = status == "cutover_already_complete"
  _assert_common_response(body, expected, completed=completed)
  if _string(body, "removal_build_sha") != expected.removal_build_sha:
    raise ReleaseError("controller postpublish changed removal_build_sha")
  if _string(body, "removal_image_digest") != expected.removal_image_digest:
    raise ReleaseError("controller postpublish changed removal_image_digest")
  _response_recoveries(
    body, require_frozen_current_match=not completed
  )
  if completed and http_status == 200:
    return "success"
  if status in {
    "redeploying",
    "redeploy_failed",
    "finalizing",
    "repair_required",
    "rolling_back",
  }:
    return "wait"
  raise ReleaseError(f"controller returned unsupported postpublish status {status!r}")


def _cutover_from_args(args: argparse.Namespace, *, bound: bool = False) -> CutoverIdentity:
  return CutoverIdentity(
    epoch=args.epoch,
    release_channel=args.release_channel,
    platform_release_ref=args.platform_release_ref,
    prerequisite_build_sha=args.prerequisite_sha,
    prerequisite_image_digest=args.prerequisite_digest,
    removal_build_sha=args.removal_sha,
    removal_image_digest=args.removal_digest if bound else "",
  )


def _load_json(path: str) -> Mapping[str, Any]:
  try:
    with Path(path).open(encoding="utf-8") as source:
      value = json.load(source)
  except (OSError, ValueError) as exc:
    raise ReleaseError("controller returned invalid JSON") from exc
  if not isinstance(value, dict):
    raise ReleaseError("controller response is not an object")
  return value


def _add_cutover_args(parser: argparse.ArgumentParser, *, bound: bool = False) -> None:
  parser.add_argument("--epoch", required=True)
  parser.add_argument("--release-channel", required=True)
  parser.add_argument("--platform-release-ref", required=True)
  parser.add_argument("--prerequisite-sha", required=True)
  parser.add_argument("--prerequisite-digest", required=True)
  parser.add_argument("--removal-sha", required=True)
  if bound:
    parser.add_argument("--removal-digest", required=True)


def _add_recovery_args(parser: argparse.ArgumentParser) -> None:
  for prefix in ("frozen", "current"):
    parser.add_argument(f"--{prefix}-recovery-sequence", required=True, type=int)
    parser.add_argument(f"--{prefix}-recovery-sha", required=True)
    parser.add_argument(f"--{prefix}-recovery-digest", required=True)


def _assert_expected_recoveries(
  body: Mapping[str, Any], args: argparse.Namespace
) -> None:
  expected_frozen = RecoveryIdentity(
    args.frozen_recovery_sequence,
    args.frozen_recovery_sha,
    args.frozen_recovery_digest,
  )
  expected_current = RecoveryIdentity(
    args.current_recovery_sequence,
    args.current_recovery_sha,
    args.current_recovery_digest,
  )
  frozen, current = _response_recoveries(
    body, require_frozen_current_match=False
  )
  if frozen != expected_frozen or current != expected_current:
    raise ReleaseError("controller changed a recovery release identity")


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser()
  commands = parser.add_subparsers(dest="command", required=True)

  for command in ("inventory", "prewrite", "final"):
    child = commands.add_parser(command)
    child.add_argument("--repository", required=True)
    child.add_argument("--prerequisite-digest", required=True)
    child.add_argument("--prerequisite-revision", required=True)
    if command == "inventory":
      child.add_argument("--output", required=True)
    elif command == "prewrite":
      child.add_argument("--target-digest", required=True)
      child.add_argument("--target-revision", required=True)
    else:
      child.add_argument("--released-digest", required=True)
      child.add_argument("--released-revision", required=True)

  worker = commands.add_parser("worker")
  worker.add_argument("--repository", required=True)
  worker.add_argument("--digest", required=True)
  worker.add_argument("--revision", required=True)

  gate = commands.add_parser("gate")
  gate.add_argument("--response", required=True)
  gate.add_argument("--http-status", required=True, type=int)
  _add_cutover_args(gate)

  bind = commands.add_parser("bind")
  bind.add_argument("--response", required=True)
  bind.add_argument("--http-status", required=True, type=int)
  _add_cutover_args(bind, bound=True)
  _add_recovery_args(bind)

  post = commands.add_parser("postpublish")
  post.add_argument("--response", required=True)
  post.add_argument("--http-status", required=True, type=int)
  _add_cutover_args(post, bound=True)
  _add_recovery_args(post)
  return parser


def main(argv: list[str] | None = None) -> int:
  args = build_parser().parse_args(argv)
  if args.command in {"inventory", "prewrite", "final"}:
    prerequisite = ImageIdentity(
      args.prerequisite_digest, args.prerequisite_revision
    )
    if args.command == "inventory":
      target = inventory_channels(args.repository, prerequisite)
      with Path(args.output).open("a", encoding="utf-8") as output:
        output.write(f"target_digest={target.digest}\n")
        output.write(f"target_revision={target.revision}\n")
      return 0
    if args.command == "prewrite":
      assert_prewrite_channels(
        args.repository,
        prerequisite,
        ImageIdentity(args.target_digest, args.target_revision),
      )
      return 0
    assert_final_channels(
      args.repository,
      prerequisite,
      ImageIdentity(args.released_digest, args.released_revision),
    )
    return 0
  if args.command == "worker":
    assert_worker_release(args.repository, ImageIdentity(args.digest, args.revision))
    return 0

  body = _load_json(args.response)
  if args.command == "gate":
    decision = classify_gate_response(
      body, args.http_status, _cutover_from_args(args)
    )
    print(
      "|".join(
        (
          decision.decision,
          decision.bound_digest,
          str(decision.frozen_recovery.sequence),
          decision.frozen_recovery.build_sha,
          decision.frozen_recovery.image_digest,
          str(decision.current_recovery.sequence),
          decision.current_recovery.build_sha,
          decision.current_recovery.image_digest,
        )
      )
    )
    return 0
  identity = _cutover_from_args(args, bound=True)
  if args.command == "bind":
    assert_bind_response(body, args.http_status, identity)
    _assert_expected_recoveries(body, args)
    return 0
  decision = classify_postpublish_response(body, args.http_status, identity)
  _assert_expected_recoveries(body, args)
  print(decision)
  return 0


if __name__ == "__main__":
  try:
    raise SystemExit(main())
  except ReleaseError as exc:
    print(f"external recovery release refused: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc
