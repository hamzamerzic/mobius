"""Gemini image generation route."""

import asyncio
import base64
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi import Path as FastPath
from fastapi import Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app import models
from app.auth import decode_access_token, decrypt_api_key
from app.config import get_settings
from app.database import get_db
from app.deps import get_current_owner

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chats", tags=["generate"])

_GEMINI_BASE = (
  "https://generativelanguage.googleapis.com/v1beta/models/"
)

# Cheapest flash model only — keeps per-image cost low (~$0.04/image).
_IMAGE_MODELS = [
  "gemini-2.5-flash-image",
]

_MAX_RETRIES = 3


_ALLOWED_ASPECT_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4"}


class GenerateRequest(BaseModel):
  prompt: str
  aspect_ratio: str = "1:1"

  @field_validator("aspect_ratio")
  @classmethod
  def validate_aspect_ratio(cls, v: str) -> str:
    if v not in _ALLOWED_ASPECT_RATIOS:
      raise ValueError(
        f"aspect_ratio must be one of {sorted(_ALLOWED_ASPECT_RATIOS)}"
      )
    return v


# The generate endpoint uses this instead of get_current_owner because
# the image serve endpoint must accept ?token= for <img> tags that
# cannot set Authorization headers.
def _auth_token(
  authorization: Optional[str] = Header(default=None),
  token: Optional[str] = Query(default=None),
) -> str:
  """Accepts a JWT from Authorization header or ?token= query param."""
  if authorization and authorization.startswith("Bearer "):
    return authorization[7:]
  if token:
    return token
  raise HTTPException(status_code=401, detail="Not authenticated.")


async def _call_gemini(
  api_key: str, prompt: str, aspect_ratio: str,
) -> tuple[bytes, str]:
  """Calls Gemini image generation with retries on transient errors."""
  payload = {
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": {
      "responseModalities": ["TEXT", "IMAGE"],
      "imageConfig": {"aspectRatio": aspect_ratio},
    },
  }

  last_error = None
  async with httpx.AsyncClient() as client:
    for model in _IMAGE_MODELS:
      log.info("Trying image generation with model: %s", model)
      url = f"{_GEMINI_BASE}{model}:generateContent"
      for attempt in range(_MAX_RETRIES):
        try:
          resp = await client.post(
            url,
            json=payload,
            headers={"x-goog-api-key": api_key},
            timeout=60.0,
          )
        except httpx.TimeoutException:
          last_error = "Gemini request timed out."
          continue

        if resp.status_code == 200:
          data = resp.json()
          for part in data.get("candidates", [{}])[0] \
              .get("content", {}).get("parts", []):
            if "inlineData" in part:
              return base64.b64decode(part["inlineData"]["data"]), model
          last_error = "Gemini returned no image in response."
          break  # no point retrying if response was 200 but no image

        if resp.status_code == 429:
          body = resp.text or ""
          if "limit: 0" in body or "quota" in body.lower():
            # Budget/quota exhausted — no point retrying.
            raise HTTPException(
              status_code=402,
              detail="Gemini API quota exhausted. Check your billing.",
            )
          # Transient rate limit — wait and retry.
          wait = 2 ** attempt
          log.warning("Gemini 429 on %s, retrying in %ds", model, wait)
          last_error = "Gemini rate limit exceeded."
          await asyncio.sleep(wait)
          continue

        # Other errors — don't retry.
        last_error = resp.text[:300] if resp.text else f"HTTP {resp.status_code}"
        log.warning("Gemini %d on %s: %s", resp.status_code, model, last_error)
        break

  raise HTTPException(status_code=502, detail=f"Image generation failed: {last_error}")


@router.post("/{chat_id}/generate-image")
async def generate_image(
  body: GenerateRequest,
  chat_id: str,
  owner: models.Owner = Depends(get_current_owner),
  db: Session = Depends(get_db),
):
  """Calls Gemini to generate an image and saves it under the chat dir."""
  if not owner.gemini_api_key_enc:
    raise HTTPException(
      status_code=503,
      detail="No Gemini API key configured. Add one in Settings.",
    )

  chat = db.query(models.Chat).filter(
    models.Chat.id == chat_id,
    models.Chat.deleted_at.is_(None),
  ).first()
  if not chat:
    raise HTTPException(status_code=404, detail="Chat not found.")

  api_key = decrypt_api_key(owner.gemini_api_key_enc)
  image_bytes, model_used = await _call_gemini(
    api_key, body.prompt, body.aspect_ratio,
  )

  settings = get_settings()
  gen_dir = Path(settings.data_dir) / "chats" / chat_id / "generated"
  gen_dir.mkdir(parents=True, exist_ok=True)
  filename = f"{uuid.uuid4().hex}.png"
  (gen_dir / filename).write_bytes(image_bytes)

  record = {
    "filename": filename,
    "prompt": body.prompt,
    "created_at": datetime.now(UTC).isoformat(),
  }
  chat.generated_images = list(chat.generated_images or []) + [record]
  db.commit()

  return {
    "url": f"/api/chats/{chat_id}/generated/{filename}",
    "model": model_used,
  }


@router.get("/{chat_id}/generated/{filename}")
def serve_generated_image(
  chat_id: str,
  filename: str = FastPath(...),
  raw_token: str = Depends(_auth_token),
  db: Session = Depends(get_db),
):
  """Serves a generated image. Accepts JWT from header or ?token= param."""
  payload = decode_access_token(raw_token)
  if not payload:
    raise HTTPException(status_code=401, detail="Invalid token.")
  owner = db.query(models.Owner).filter(
    models.Owner.username == payload.get("sub")
  ).first()
  if not owner:
    raise HTTPException(status_code=401, detail="Owner not found.")

  settings = get_settings()
  gen_dir = Path(settings.data_dir) / "chats" / chat_id / "generated"
  file_path = (gen_dir / filename).resolve()

  if not file_path.is_relative_to(gen_dir.resolve()):
    raise HTTPException(status_code=400, detail="Invalid path.")
  if not file_path.exists():
    raise HTTPException(status_code=404, detail="Image not found.")

  return FileResponse(str(file_path), media_type="image/png")
