"""VAPID key management and Web Push delivery."""

import base64
import json
import logging
from pathlib import Path

from py_vapid import Vapid
from pywebpush import webpush, WebPushException

from app.config import get_settings

logger = logging.getLogger(__name__)

_vapid: Vapid | None = None


def _key_dir() -> Path:
  settings = get_settings()
  return Path(settings.data_dir) / "push"


def init_vapid():
  """Load or generate VAPID keys. Call once at startup."""
  global _vapid
  d = _key_dir()
  d.mkdir(parents=True, exist_ok=True)
  priv = d / "private_key.pem"
  pub = d / "public_key.pem"
  v = Vapid()
  if priv.exists():
    v = Vapid.from_pem(priv.read_bytes())
  else:
    v.generate_keys()
    priv.write_bytes(v.private_pem())
    pub.write_bytes(v.public_pem())
    logger.info("Generated new VAPID keys in %s", d)
  _vapid = v


def get_public_key_base64url() -> str:
  """Return the VAPID public key as a base64url-encoded string."""
  if _vapid is None:
    raise RuntimeError("VAPID not initialized — call init_vapid() first")
  raw = _vapid.public_key.public_bytes(
    encoding=__import__("cryptography").hazmat.primitives.serialization.Encoding.X962,
    format=__import__("cryptography").hazmat.primitives.serialization.PublicFormat.UncompressedPoint,
  )
  return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def get_vapid_claims() -> dict:
  """Return VAPID claims dict for pywebpush."""
  settings = get_settings()
  return {"sub": f"mailto:admin@{settings.domain}"}


def send_push(subscription_info: dict, payload: dict) -> bool:
  """Send a Web Push notification. Returns True on success, False on gone."""
  if _vapid is None:
    raise RuntimeError("VAPID not initialized — call init_vapid() first")
  try:
    # Pass the Vapid instance directly — pywebpush accepts it and
    # avoids the PEM-vs-raw-key parsing ambiguity in from_string().
    webpush(
      subscription_info=subscription_info,
      data=json.dumps(payload),
      vapid_private_key=_vapid,
      vapid_claims=get_vapid_claims(),
      content_encoding="aes128gcm",
    )
    return True
  except WebPushException as e:
    if e.response is not None and e.response.status_code == 410:
      return False
    logger.error("Web Push failed: %s", e)
    raise
