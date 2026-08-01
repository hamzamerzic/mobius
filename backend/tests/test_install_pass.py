"""One-time install passes carry an owner session onto the iOS home screen.

iOS gives every home-screen web app its own storage container, sealed off from
Safari and from every other installed app on the same origin. An app installed
from a signed-in Safari session therefore launches signed out, and the owner
meets a login screen once per app they install.

A pass is a short-lived scoped wrapper around an ordinary owner token (the same
shape as the managed-SSO handoff). It travels in the manifest's `start_url`, is
redeemed on the installed app's first launch, and is spent on use. These tests
pin the properties that make that safe: it must be owner-authenticated to mint,
bound to one app, single-use, and never cached anywhere along the way.
"""

from datetime import timedelta

from app import auth as auth_lib
from test_app_fixtures import create_local_app


def _create_app(client, auth_header, name="Notes"):
  return create_local_app(client, auth_header, name=name)


def _mint(client, auth_header, slug):
  return client.post("/api/auth/install-pass", json={"slug": slug},
                     headers=auth_header)


def test_pass_round_trips_into_the_session_it_wraps(client, auth, db):
  app_row = _create_app(client, auth)
  slug = app_row["slug"]

  minted = _mint(client, auth, slug)
  assert minted.status_code == 200
  pass_token = minted.json()["install_pass"]
  # A credential must not be storable by any cache along the way.
  assert minted.headers["cache-control"] == "no-store"

  redeemed = client.post("/api/auth/install-pass/redeem",
                         json={"install_pass": pass_token, "slug": slug})
  assert redeemed.status_code == 200
  access_token = redeemed.json()["access_token"]
  assert redeemed.headers["cache-control"] == "no-store"

  # The redeemed token is an ordinary owner session, not a new kind of thing.
  payload = auth_lib.decode_access_token(access_token)
  assert payload["sub"] == "test"
  assert "scope" not in payload
  me = client.get("/api/apps/",
                  headers={"Authorization": f"Bearer {access_token}"})
  assert me.status_code == 200


def test_minting_requires_the_session_being_handed_over(client, auth):
  app_row = _create_app(client, auth)
  # Anonymous callers cannot mint themselves a way in.
  assert client.post("/api/auth/install-pass",
                     json={"slug": app_row["slug"]}).status_code == 401


def test_a_pass_is_spent_on_first_use(client, auth):
  app_row = _create_app(client, auth)
  slug = app_row["slug"]
  pass_token = _mint(client, auth, slug).json()["install_pass"]

  body = {"install_pass": pass_token, "slug": slug}
  assert client.post("/api/auth/install-pass/redeem", json=body).status_code == 200
  replay = client.post("/api/auth/install-pass/redeem", json=body)
  assert replay.status_code == 401
  assert "already been used" in replay.json()["detail"]


def test_a_pass_is_bound_to_the_app_it_was_minted_for(client, auth):
  first = _create_app(client, auth, name="Notes")
  second = _create_app(client, auth, name="Timer")
  pass_token = _mint(client, auth, first["slug"]).json()["install_pass"]

  stolen = client.post("/api/auth/install-pass/redeem",
                       json={"install_pass": pass_token, "slug": second["slug"]})
  assert stolen.status_code == 401
  # Still spendable for its own app: rejecting the wrong app must not burn it.
  ok = client.post("/api/auth/install-pass/redeem",
                   json={"install_pass": pass_token, "slug": first["slug"]})
  assert ok.status_code == 200


def test_expired_and_forged_passes_are_refused(client, auth):
  app_row = _create_app(client, auth)
  slug = app_row["slug"]

  expired = auth_module_expired_pass(slug)
  assert client.post("/api/auth/install-pass/redeem",
                     json={"install_pass": expired, "slug": slug}).status_code == 401

  # A validly-signed token of the WRONG scope must not be usable as a pass:
  # otherwise any leaked media/app token becomes a home-screen sign-in.
  wrong_scope = auth_lib.create_access_token(
    {"scope": "media", "access_token": "x", "app_slug": slug},
    expires_delta=timedelta(minutes=5),
  )
  assert client.post("/api/auth/install-pass/redeem",
                     json={"install_pass": wrong_scope, "slug": slug}).status_code == 401

  assert client.post("/api/auth/install-pass/redeem",
                     json={"install_pass": "not-a-jwt", "slug": slug}).status_code == 401


def auth_module_expired_pass(slug):
  return auth_lib.create_install_pass(
    owner_username="test", token_epoch=0, app_slug=slug,
    expires_delta=timedelta(seconds=-1),
  )


def test_manifest_forwards_a_pass_into_start_url_without_caching_it(client, auth):
  app_row = _create_app(client, auth)
  slug = app_row["slug"]
  base = f"/apps/{slug}/"

  plain = client.get(f"{base}manifest.json")
  assert plain.status_code == 200
  assert plain.json()["start_url"] == base
  assert plain.headers["cache-control"] == "no-cache, must-revalidate"

  carried = client.get(f"{base}manifest.json", params={"pass": "abc.def.ghi"})
  assert carried.status_code == 200
  assert carried.json()["start_url"] == f"{base}?pass=abc.def.ghi"
  # scope stays the app root, or the installed PWA would not treat its own
  # launch URL as in-scope.
  assert carried.json()["scope"] == base
  assert carried.headers["cache-control"] == "no-store"


def test_manifest_never_mints_a_pass_for_an_anonymous_fetch(client, auth):
  app_row = _create_app(client, auth)
  slug = app_row["slug"]
  body = client.get(f"/apps/{slug}/manifest.json").json()
  assert "pass" not in body["start_url"]
