# Managed core digest releases

`core-digest-image.yml` publishes recurring managed-core releases from the
protected `stack/external-recovery-v1` branch. It does not replace or modify the
historical one-time external-Recovery cutover workflow.

There are two distinct core identities:

- The frozen compatibility floor remains
  `46cac47ef7082f0ddebc8f63f3bf0bcce9353b5e` at
  `sha256:c85a50babb768e036cf1db748efbec6e26b846b2172379d0cadac0d2d162dddd`.
  The public `:main` and `:external-recovery` tags stay at that identity.
- The moving managed-core prerequisite is the controller's latest completed
  digest. The first recurring release starts from
  `e98a281431d91071364409284c3b3c5797c335c4` at
  `sha256:acff72f92a1c6192e2e3bc9fc3c9731459abc59662d38ec7c6e6f445ddc390e8`.

The authenticated `GET /internal/core-releases/current` response is the source
of truth for the moving identity. Protected repository variables (or explicit
manual inputs) express release intent and must match it exactly. The workflow
also proves the registry digest's baked revision and verifies that the
prerequisite commit is an ancestor of the candidate before any registry write.

## One-time activation

Deploy the controller support for the authenticated current-core endpoint and
next-generation admission first. Confirm that it reports the e98/acff identity,
then configure release intent without changing the frozen compatibility vars.
Keep the historical `MOBIUS_EXTERNAL_RECOVERY_RELEASE_ENABLED` variable
`false`:

```bash
gh variable set MOBIUS_MANAGED_CORE_PREREQUISITE_SHA \
  --repo mobius-os/mobius \
  --body e98a281431d91071364409284c3b3c5797c335c4
gh variable set MOBIUS_MANAGED_CORE_PREREQUISITE_DIGEST \
  --repo mobius-os/mobius \
  --body sha256:acff72f92a1c6192e2e3bc9fc3c9731459abc59662d38ec7c6e6f445ddc390e8
gh variable set MOBIUS_MANAGED_CORE_RELEASE_ENABLED \
  --repo mobius-os/mobius \
  --body true
```

The protected `external-recovery-release` environment must already provide
`MOBIUS_YOU_CORE_RELEASE_URL` and `MOBIUS_YOU_CORE_RELEASE_TOKEN`. The job token
receives only `contents: read` and `packages: write`.

## Release and replay

A push to the protected branch starts the release. A manual run can make the
prerequisite explicit:

```bash
gh workflow run core-digest-image.yml \
  --repo mobius-os/mobius \
  --ref stack/external-recovery-v1 \
  -f prerequisite_sha=e98a281431d91071364409284c3b3c5797c335c4 \
  -f prerequisite_digest=sha256:acff72f92a1c6192e2e3bc9fc3c9731459abc59662d38ec7c6e6f445ddc390e8
```

Prepublish freezes and audits the fleet before registry login. The workflow
then builds one attempt-specific tag, binds its immutable digest, asks the
controller to deploy that digest, and waits for both fleet completion and the
new completed current-core identity. A rerun resumes only the exact bound
tuple. If branch HEAD already equals the controller's completed identity, the
workflow verifies the digest and exits without mutating the controller or
registry.

If a job is interrupted after its digest is bound and the protected branch
advances, resume that durable older owner by passing its exact SHA as
`candidate_sha` along with its original prerequisite. An unbound build must
still be protected-branch HEAD immediately before bind; the workflow rechecks
the remote ref after its audit and build. A push may publish only its own exact
branch head, and the older-candidate input is accepted only for the exact
already-bound controller tuple. An `awaiting_replacement` generation accepts
only a different protected-branch HEAD, so the failed candidate cannot be
mistaken for a fresh release.

After a successful release, advance the two `MOBIUS_MANAGED_CORE_PREREQUISITE_*`
variables together to the completed SHA and digest before publishing its
successor. Never advance the frozen `MOBIUS_EXTERNAL_RECOVERY_PREREQUISITE_*`
variables and never retag `:external-recovery`.
