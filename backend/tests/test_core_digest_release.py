from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
  "core_digest_release", SCRIPTS / "core_digest_release.py"
)
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)

CURRENT_SHA = "a" * 40
CANDIDATE_SHA = "b" * 40
FAILED_SHA = "e" * 40
CURRENT_DIGEST = "sha256:" + "c" * 64
CANDIDATE_DIGEST = "sha256:" + "d" * 64
CHANNEL = "ghcr.io/mobius-os/mobius:external-recovery"
RELEASE_REF = "refs/heads/stack/external-recovery-v1"


def current_response(**changes):
  body = {
    "status": "completed",
    "generation": 7,
    "build_sha": CURRENT_SHA,
    "image_digest": CURRENT_DIGEST,
    "release_channel": CHANNEL,
    "platform_release_ref": RELEASE_REF,
  }
  body.update(changes)
  return body


def classify(
  body,
  *,
  candidate=CANDIDATE_SHA,
  branch_head=CANDIDATE_SHA,
  status=200,
):
  return release.classify_current_response(
    body,
    status,
    prerequisite=release.ImageIdentity(CURRENT_DIGEST, CURRENT_SHA),
    candidate_sha=candidate,
    candidate_epoch=f"managed-core-v1-{candidate}",
    branch_head_sha=branch_head,
    release_channel=CHANNEL,
    platform_release_ref=RELEASE_REF,
  )


def test_current_core_requires_exact_completed_controller_identity():
  decision = classify(current_response())
  assert decision.decision == "release"
  assert decision.current == release.CurrentCoreIdentity(
    7, CURRENT_SHA, CURRENT_DIGEST, CHANNEL, RELEASE_REF
  )

  replay = classify(current_response(), candidate=CURRENT_SHA)
  assert replay.decision == "replay"

  with pytest.raises(release.ReleaseError, match="protected branch HEAD"):
    classify(current_response(), candidate=FAILED_SHA)


def test_active_core_allows_only_the_exact_candidate_tuple():
  active = current_response(
    status="active",
    cutover_status="publish_authorized",
    active_epoch=f"managed-core-v1-{CANDIDATE_SHA}",
    active_build_sha=CANDIDATE_SHA,
    active_image_digest=CANDIDATE_DIGEST,
  )
  decision = classify(active, branch_head=FAILED_SHA)
  assert decision.decision == "resume"
  assert decision.active_image_digest == CANDIDATE_DIGEST

  unbound = dict(active, active_image_digest="")
  with pytest.raises(release.ReleaseError, match="unbound active candidate"):
    classify(unbound, branch_head=FAILED_SHA)
  assert classify(unbound).decision == "resume"

  with pytest.raises(release.ReleaseError, match="exact active controller tuple"):
    classify(active, candidate=FAILED_SHA, branch_head=FAILED_SHA)

  active["active_epoch"] = f"managed-core-v1-{FAILED_SHA}"
  with pytest.raises(release.ReleaseError, match="exact active controller tuple"):
    classify(active)


def test_awaiting_replacement_accepts_only_a_new_branch_head():
  replacement = current_response(
    status="awaiting_replacement",
    cutover_status="awaiting_replacement",
    active_epoch=f"managed-core-v1-{FAILED_SHA}",
    active_build_sha=FAILED_SHA,
    active_image_digest=CANDIDATE_DIGEST,
  )
  decision = classify(replacement)
  assert decision.decision == "replacement"
  assert decision.active_image_digest == ""

  with pytest.raises(release.ReleaseError, match="protected branch HEAD"):
    classify(replacement, branch_head=FAILED_SHA)
  with pytest.raises(release.ReleaseError, match="supersede the failed candidate"):
    classify(replacement, candidate=FAILED_SHA, branch_head=FAILED_SHA)


@pytest.mark.parametrize(
  ("changes", "message"),
  (
    ({"status": "redeploying"}, "unsupported current-core status"),
    ({"generation": 0}, "completed core generation"),
    ({"build_sha": CANDIDATE_SHA}, "protected release prerequisite"),
    ({"image_digest": CANDIDATE_DIGEST}, "protected release prerequisite"),
    ({"release_channel": "ghcr.io/example/wrong"}, "release_channel"),
    ({"platform_release_ref": "refs/heads/main"}, "platform_release_ref"),
  ),
)
def test_current_core_rejects_ambiguous_or_changed_state(changes, message):
  with pytest.raises(release.ReleaseError, match=message):
    classify(current_response(**changes))


def test_current_core_rejects_non_success_response():
  with pytest.raises(release.ReleaseError, match=r"HTTP 409 \(core_release_active\)"):
    classify({"error": "core_release_active"}, status=409)


def test_exact_image_requires_both_digest_and_revision(monkeypatch):
  expected = release.ImageIdentity(CURRENT_DIGEST, CURRENT_SHA)
  monkeypatch.setattr(release, "inspect_digest", lambda *_args: expected)
  release.assert_exact_image("ghcr.io/mobius-os/mobius", expected)

  monkeypatch.setattr(
    release,
    "inspect_digest",
    lambda *_args: release.ImageIdentity(CURRENT_DIGEST, CANDIDATE_SHA),
  )
  with pytest.raises(release.ReleaseError, match="expected revision"):
    release.assert_exact_image("ghcr.io/mobius-os/mobius", expected)


def test_payload_is_canonical_and_bound_digest_is_explicit(tmp_path):
  path = tmp_path / "payload.json"
  identity = release.CutoverIdentity(
    epoch=f"managed-core-v1-{CANDIDATE_SHA}",
    release_channel=CHANNEL,
    platform_release_ref=RELEASE_REF,
    prerequisite_build_sha=CURRENT_SHA,
    prerequisite_image_digest=CURRENT_DIGEST,
    removal_build_sha=CANDIDATE_SHA,
  )
  release.write_payload(str(path), identity)
  body = json.loads(path.read_text(encoding="utf-8"))
  assert body == {
    "epoch": f"managed-core-v1-{CANDIDATE_SHA}",
    "release_channel": CHANNEL,
    "platform_release_ref": RELEASE_REF,
    "prerequisite_build_sha": CURRENT_SHA,
    "prerequisite_image_digest": CURRENT_DIGEST,
    "removal_build_sha": CANDIDATE_SHA,
  }
  assert "removal_image_digest" not in body

  release.write_payload(
    str(path),
    replace(identity, removal_image_digest=CANDIDATE_DIGEST),
  )
  assert json.loads(path.read_text(encoding="utf-8"))[
    "removal_image_digest"
  ] == CANDIDATE_DIGEST
