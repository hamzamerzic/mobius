"""Submit failures must read as one sentence, never as a terminal transcript."""

from app.contribution_errors import (
  ContributionSubmitError,
  push_rejected,
  readable_output,
)

# The exact bytes a rejected Send stored on a real contribution record: the
# local gate's colour codes, npm's lifecycle banner, and the one line that
# actually explains the refusal.
REAL_PRE_PUSH_REJECTION = (
  "\x1b[1;31m[pre-push]\x1b[0m frontend-unit FAILED:\r\n"
  "    \r\n"
  "    > moebius@0.1.0 test\r\n"
  "    > npm run test:lib && npm run test:hooks\r\n"
  "    \r\n"
  "    \r\n"
  "    > moebius@0.1.0 pretest:lib\r\n"
  "    > npm run runtime:check && npm run test:structure\r\n"
  "    \r\n"
  "    Structural-test debt grew:\r\n"
  "      - 781 source-reading cases exceeds 780\r\n"
  "    Replace implementation-text assertions with behavioral coverage.\r\n"
  "\x1b[1;31m[pre-push]\x1b[0m push blocked. Fix the above.\r\n"
)


def test_terminal_colour_never_survives_into_stored_text():
  cleaned = readable_output(REAL_PRE_PUSH_REJECTION)

  assert "\x1b" not in cleaned
  assert "[1;31m" not in cleaned
  assert "[pre-push] frontend-unit FAILED:" in cleaned
  assert "781 source-reading cases exceeds 780" in cleaned


def test_blank_runs_collapse_and_line_endings_normalize():
  cleaned = readable_output("first\r\n\r\n\r\n\r\nsecond   \r\n\r\n")

  assert cleaned == "first\n\nsecond"


def test_overflow_keeps_the_end_where_the_reason_is():
  raw = "\n".join(["banner line"] * 400 + ["the actual reason"])

  cleaned = readable_output(raw, limit=200)

  assert cleaned.startswith("…\n")
  assert cleaned.endswith("the actual reason")
  assert len(cleaned) <= 210


def test_stray_control_bytes_are_removed_but_text_is_kept():
  cleaned = readable_output("before\x00\x07after\ttabbed")

  assert cleaned == "beforeafter\ttabbed"


def test_local_gate_rejection_names_the_check_and_hides_the_transcript():
  error = push_rejected(REAL_PRE_PUSH_REJECTION)

  assert isinstance(error, ContributionSubmitError)
  assert error.message == (
    "This did not pass the checks Möbius runs before publishing "
    "(frontend-unit). Nothing was published — fix it locally, then send again."
  )
  assert "\x1b" not in error.message
  assert "npm run" not in error.message
  # The evidence is still reachable, just not the headline.
  assert "781 source-reading cases exceeds 780" in error.detail


def test_several_failing_checks_are_all_named_once():
  error = push_rejected(
    "[pre-push] frontend-unit FAILED:\n"
    "    boom\n"
    "[pre-push] backend pytest FAILED:\n"
    "    boom\n"
    "[pre-push] frontend-unit FAILED:\n"
    "[pre-push] push blocked. Fix the above.\n"
  )

  assert "(frontend-unit, backend pytest)" in error.message


def test_privacy_rejection_gets_its_own_sentence():
  error = push_rejected(
    "[pre-push] private workspace path staged: .claude/settings.json\n"
    "[pre-push] push blocked by the privacy gate. Do not use --no-verify.\n"
  )

  assert "privacy gate" in error.message
  assert "Nothing was published." in error.message


def test_an_unrecognized_refusal_is_attributed_to_github_not_to_us():
  error = push_rejected(
    "remote: Permission to mobius-os/mobius.git denied.\n"
    "fatal: unable to access 'https://github.com/...': 403\n"
  )

  assert error.message == (
    "GitHub would not accept this branch, so nothing was published."
  )
  assert "403" in error.detail


def test_a_silent_failure_still_says_nothing_was_published():
  error = push_rejected("")

  assert error.message == "The push failed, so nothing was published."
  assert error.detail == ""


def test_the_record_patch_survives_classification():
  error = push_rejected("boom", record_patch={"head_repository": "owner/fork"})

  assert error.record_patch == {"head_repository": "owner/fork"}
