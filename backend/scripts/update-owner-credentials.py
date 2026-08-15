#!/usr/bin/env python3
"""Consume owner credentials as stdin JSON and print only a safe outcome."""

from __future__ import annotations

import json
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
  sys.path.insert(0, str(BACKEND_ROOT))

from app import auth, models
from app.config import get_settings
from app.database import SessionLocal
from app.routes.auth import _write_service_token


def main() -> int:
  try:
    values = json.load(sys.stdin)
  except Exception:
    print("Credential input was invalid.")
    return 2
  if not isinstance(values, dict):
    print("Credential input was invalid.")
    return 2

  db = SessionLocal()
  try:
    owner = db.query(models.Owner).one_or_none()
    if owner is None:
      print("Owner account was not found.")
      return 1
    if get_settings().mobius_sso_enabled:
      print("This instance uses managed sign-in.")
      return 1

    current_password = values.get("current_password", "")
    new_username = values.get("new_username", "").strip()
    new_password = values.get("new_password", "")
    confirm_password = values.get("confirm_password", "")
    if not auth.verify_password(current_password, owner.hashed_password):
      print("Current password is incorrect.")
      return 1
    if not 1 <= len(new_username) <= 64:
      print("Username must be 1–64 characters.")
      return 1
    if not new_password.strip() or len(new_password) > 1024:
      print("Password cannot be blank or longer than 1024 characters.")
      return 1
    if new_password != confirm_password:
      print("New passwords do not match.")
      return 1

    owner.username = new_username
    owner.hashed_password = auth.hash_password(new_password)
    owner.token_epoch += 1
    epoch = owner.token_epoch
    db.commit()
  except Exception:
    db.rollback()
    print("Credentials could not be changed.")
    return 1
  finally:
    values.clear()
    db.close()

  try:
    _write_service_token(new_username, epoch)
  except OSError:
    print(
      "Credentials changed. Sign in again, then restart Möbius to refresh "
      "background access."
    )
    return 0
  print("Credentials changed. Sign in again with the new details.")
  return 0


if __name__ == "__main__":
  sys.exit(main())
