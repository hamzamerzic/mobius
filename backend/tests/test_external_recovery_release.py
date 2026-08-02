from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
  "external_recovery_release", ROOT / "scripts" / "external_recovery_release.py"
)
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)

A_SHA = "a" * 40
B_SHA = "b" * 40
C_SHA = "c" * 40
D_SHA = "d" * 40
A_DIGEST = "sha256:" + "a" * 64
B_DIGEST = "sha256:" + "b" * 64
R_DIGEST = "sha256:" + "c" * 64
NEXT_R_DIGEST = "sha256:" + "d" * 64
CHANNEL = "ghcr.io/mobius-os/mobius:external-recovery"
RELEASE_REF = "refs/heads/stack/external-recovery-v1"
EXPECTED = release.CutoverIdentity(
  epoch=f"external-recovery-v1-{B_SHA}",
  release_channel=CHANNEL,
  platform_release_ref=RELEASE_REF,
  prerequisite_build_sha=A_SHA,
  prerequisite_image_digest=A_DIGEST,
  removal_build_sha=B_SHA,
)


def response(
  *,
  status="auditing",
  removal_sha=B_SHA,
  removal_digest="",
  current_sequence=123,
  current_sha=C_SHA,
  current_digest=R_DIGEST,
):
  return {
    "status": status,
    "epoch": EXPECTED.epoch,
    "release_channel": CHANNEL,
    "platform_release_ref": RELEASE_REF,
    "prerequisite_build_sha": A_SHA,
    "prerequisite_image_digest": A_DIGEST,
    "removal_build_sha": removal_sha,
    "removal_image_digest": removal_digest,
    "recovery_release_sequence": 123,
    "recovery_build_sha": C_SHA,
    "recovery_image_digest": R_DIGEST,
    "current_recovery_release_sequence": current_sequence,
    "current_recovery_build_sha": current_sha,
    "current_recovery_image_digest": current_digest,
    "approved_recovery_release_sequence": current_sequence,
    "approved_recovery_build_sha": current_sha,
    "approved_recovery_image_digest": current_digest,
    "job_status": "running",
    "failed": 0,
    "completed": 0,
    "total": 1,
  }


def test_gate_builds_only_after_exact_completed_audit():
  auditing = release.classify_gate_response(response(), 202, EXPECTED)
  assert auditing.decision == "wait"

  ready = response(status="awaiting_redeploy")
  ready.update(job_status="completed", completed=1)
  decision = release.classify_gate_response(ready, 202, EXPECTED)
  assert decision.decision == "build_cutover"
  assert decision.bound_digest == ""
  assert decision.frozen_recovery == release.RecoveryIdentity(123, C_SHA, R_DIGEST)
  assert decision.current_recovery == decision.frozen_recovery

  ready["failed"] = 1
  assert release.classify_gate_response(ready, 202, EXPECTED).decision == "wait"


def test_gate_resumes_only_an_exact_durably_bound_digest():
  active = response(status="publish_authorized", removal_digest=B_DIGEST)
  decision = release.classify_gate_response(active, 202, EXPECTED)
  assert decision.decision == "resume_cutover"
  assert decision.bound_digest == B_DIGEST

  active["removal_image_digest"] = ""
  with pytest.raises(release.ReleaseError, match="bound removal digest"):
    release.classify_gate_response(active, 202, EXPECTED)


def test_completed_b_is_noop_but_later_head_is_normal_release():
  completed = response(
    status="cutover_already_complete", removal_digest=B_DIGEST
  )
  replay = release.classify_gate_response(completed, 200, EXPECTED)
  assert replay.decision == "completed_replay"
  assert replay.bound_digest == B_DIGEST

  later = release.CutoverIdentity(
    epoch=f"external-recovery-v1-{C_SHA}",
    release_channel=CHANNEL,
    platform_release_ref=RELEASE_REF,
    prerequisite_build_sha=A_SHA,
    prerequisite_image_digest=A_DIGEST,
    removal_build_sha=C_SHA,
  )
  normal = release.classify_gate_response(completed, 200, later)
  assert normal.decision == "normal_release"

  advanced = response(
    status="cutover_already_complete",
    removal_digest=B_DIGEST,
    current_sequence=124,
    current_sha=D_SHA,
    current_digest=NEXT_R_DIGEST,
  )
  advanced_normal = release.classify_gate_response(advanced, 200, later)
  assert advanced_normal.frozen_recovery == release.RecoveryIdentity(
    123, C_SHA, R_DIGEST
  )
  assert advanced_normal.current_recovery == release.RecoveryIdentity(
    124, D_SHA, NEXT_R_DIGEST
  )


def test_gate_fails_if_channel_or_frozen_worker_identity_is_missing():
  invalid = response()
  invalid["release_channel"] = "ghcr.io/mobius-os/mobius:main"
  with pytest.raises(release.ReleaseError, match="release_channel"):
    release.classify_gate_response(invalid, 202, EXPECTED)

  invalid = response()
  invalid["recovery_release_sequence"] = 0
  with pytest.raises(release.ReleaseError, match="recovery release sequence"):
    release.classify_gate_response(invalid, 202, EXPECTED)

  invalid = response()
  invalid.pop("current_recovery_image_digest")
  with pytest.raises(release.ReleaseError, match="current_recovery image digest"):
    release.classify_gate_response(invalid, 202, EXPECTED)

  invalid = response()
  invalid["approved_recovery_build_sha"] = D_SHA
  with pytest.raises(release.ReleaseError, match="aliases disagree"):
    release.classify_gate_response(invalid, 202, EXPECTED)

  invalid = response(current_sequence=124, current_sha=D_SHA, current_digest=NEXT_R_DIGEST)
  with pytest.raises(release.ReleaseError, match="no longer frozen"):
    release.classify_gate_response(invalid, 202, EXPECTED)

  with pytest.raises(release.ReleaseError, match="HTTP 409"):
    release.classify_gate_response({"error": "cutover_tuple_conflict"}, 409, EXPECTED)


def test_bind_and_postpublish_require_the_whole_bound_tuple():
  bound = replace(EXPECTED, removal_image_digest=B_DIGEST)
  bind = response(status="publish_authorized", removal_digest=B_DIGEST)
  bind["publish_permitted"] = True
  release.assert_bind_response(bind, 200, bound)

  changed = dict(bind, removal_image_digest="sha256:" + "d" * 64)
  with pytest.raises(release.ReleaseError, match="removal_image_digest"):
    release.assert_bind_response(changed, 200, bound)

  final = response(status="cutover_already_complete", removal_digest=B_DIGEST)
  assert release.classify_postpublish_response(final, 200, bound) == "success"
  rolling = response(status="rolling_back", removal_digest=B_DIGEST)
  assert release.classify_postpublish_response(rolling, 202, bound) == "wait"


def test_legacy_and_target_state_machine_is_exact():
  prerequisite = release.ImageIdentity(A_DIGEST, A_SHA)
  target = release.ImageIdentity(B_DIGEST, B_SHA)
  release.assert_frozen_legacy(main=prerequisite, daily=None, prerequisite=prerequisite)

  with pytest.raises(release.ReleaseError, match=":main"):
    release.assert_frozen_legacy(main=target, daily=None, prerequisite=prerequisite)
  with pytest.raises(release.ReleaseError, match=":daily"):
    release.assert_frozen_legacy(
      main=prerequisite, daily=prerequisite, prerequisite=prerequisite
    )


def test_registry_absence_requires_repeated_reference_specific_not_found():
  repository = "ghcr.io/mobius-os/mobius"
  reference = f"{repository}:daily"

  def absent_runner(*_args, **_kwargs):
    return subprocess.CompletedProcess([], 1, "", f"ERROR: {reference}: not found")

  assert release.inspect_tag(
    repository,
    "daily",
    attempts=2,
    runner=absent_runner,
    sleeper=lambda _seconds: None,
  ) is None

  def ambiguous_runner(*_args, **_kwargs):
    return subprocess.CompletedProcess([], 1, "", "ERROR: docker builder unavailable")

  with pytest.raises(release.ReleaseError, match="ambiguous registry failure"):
    release.inspect_tag(
      repository,
      "daily",
      attempts=2,
      runner=ambiguous_runner,
      sleeper=lambda _seconds: None,
    )


def test_worker_stable_must_equal_the_controller_frozen_identity(monkeypatch):
  expected = release.ImageIdentity(R_DIGEST, C_SHA)
  monkeypatch.setattr(release, "inspect_tag", lambda *_args, **_kwargs: expected)
  release.assert_worker_release("ghcr.io/mobius-os/mobius-recovery", expected)

  wrong = release.ImageIdentity("sha256:" + "d" * 64, C_SHA)
  monkeypatch.setattr(release, "inspect_tag", lambda *_args, **_kwargs: wrong)
  with pytest.raises(release.ReleaseError, match="does not match"):
    release.assert_worker_release("ghcr.io/mobius-os/mobius-recovery", expected)
