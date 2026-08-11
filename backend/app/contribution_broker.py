"""Narrow client for the root-owned Möbius contribution relay surface."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_SOCKET = "/data/run/mobius-identity-broker.sock"
CONTRIBUTION_PREFIX = "/v1/contributions"
MAX_RESPONSE_BYTES = 1_000_000
_CONTRIBUTION_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")


@dataclass(frozen=True)
class ContributionBrokerError(Exception):
  status_code: int
  detail: str
  code: str = "contribution_unavailable"
  retry_after: int | None = None


def canonical_body(value: Any | None) -> bytes:
  if value is None:
    return b""
  return json.dumps(
    value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
  ).encode("utf-8")


def bound_request_id(
  method: str, path: str, body: bytes, idempotency_key: str | None,
) -> str:
  material = b"mobius-contribution-bff-v1\0"
  material += method.upper().encode("ascii") + b"\0" + path.encode("utf-8")
  material += b"\0" + (idempotency_key or "").encode("utf-8") + b"\0" + body
  return "contribution:" + hashlib.sha256(material).hexdigest()


class ContributionBrokerClient:
  def __init__(
    self,
    *,
    socket_path: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
  ) -> None:
    self.socket_path = socket_path or os.environ.get(
      "MOBIUS_IDENTITY_BROKER_SOCKET", DEFAULT_SOCKET,
    )
    self.transport = transport

  @staticmethod
  def _allowed(method: str, path: str) -> bool:
    return (
      method == "POST" and path == CONTRIBUTION_PREFIX
    ) or (
      method == "DELETE" and path == CONTRIBUTION_PREFIX + "/github"
    ) or (
      method == "GET" and path == CONTRIBUTION_PREFIX + "/github/status"
    ) or (
      method == "GET"
      and path.startswith(CONTRIBUTION_PREFIX + "/")
      and _CONTRIBUTION_ID.fullmatch(path.removeprefix(CONTRIBUTION_PREFIX + "/"))
      is not None
    )

  async def request(
    self,
    method: str,
    path: str,
    *,
    body: Any | None = None,
    idempotency_key: str | None = None,
  ) -> tuple[Any, int, dict[str, str]]:
    method = method.upper()
    if not self._allowed(method, path):
      raise ValueError("contribution broker path is outside its allow-list")
    if method in {"POST", "DELETE"} and not _IDEMPOTENCY_KEY.fullmatch(
      str(idempotency_key or "")
    ):
      raise ContributionBrokerError(
        400, "A valid Idempotency-Key is required.", "invalid_idempotency_key",
      )
    encoded = canonical_body(body)
    headers = {
      "Accept": "application/json",
      "X-Mobius-Request-Id": bound_request_id(
        method, path, encoded, idempotency_key,
      ),
    }
    if encoded:
      headers["Content-Type"] = "application/json"
    if idempotency_key:
      headers["Idempotency-Key"] = idempotency_key
    transport = self.transport or httpx.AsyncHTTPTransport(uds=self.socket_path)
    try:
      async with httpx.AsyncClient(
        transport=transport,
        base_url="http://mobius-identity-broker",
        timeout=120.0,
        follow_redirects=False,
      ) as client:
        response = await client.request(
          method, path, content=encoded if encoded else None, headers=headers,
        )
    except httpx.HTTPError as exc:
      raise ContributionBrokerError(
        503, "The Möbius contribution service could not be reached.",
      ) from exc
    if len(response.content) > MAX_RESPONSE_BYTES:
      raise ContributionBrokerError(
        502, "The Möbius contribution service response was too large."
      )
    try:
      payload = response.json() if response.content else {}
    except ValueError as exc:
      raise ContributionBrokerError(
        502, "The Möbius contribution service returned an invalid response."
      ) from exc
    response_headers = {
      key.lower(): value for key, value in response.headers.items()
      if key.lower() in {"retry-after"}
    }
    if response.is_error:
      error = payload.get("error") if isinstance(payload, dict) else None
      if isinstance(error, dict):
        detail = str(error.get("message") or "The contribution request failed.")
        code = str(error.get("code") or "contribution_error")
        retry_after = error.get("retry_after")
      else:
        detail = "The contribution request failed."
        code = "contribution_error"
        retry_after = None
      try:
        retry_after = int(
          retry_after or response_headers.get("retry-after") or 0
        ) or None
      except (TypeError, ValueError):
        retry_after = None
      raise ContributionBrokerError(
        response.status_code, detail, code, retry_after,
      )
    return payload, response.status_code, response_headers


contribution_broker = ContributionBrokerClient()
