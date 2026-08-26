"""Narrow async client for the root-owned runtime identity broker."""

from __future__ import annotations

import os
from typing import Any

import httpx


DEFAULT_SOCKET = "/run/mobius-identity-broker.sock"


async def broker_request(
  method: str,
  route: str,
  payload: dict[str, Any] | None = None,
  *,
  timeout: float = 10.0,
) -> dict[str, Any]:
  """Call one private identity route over the broker's Unix socket."""
  socket_path = os.environ.get("MOBIUS_IDENTITY_BROKER_SOCKET", DEFAULT_SOCKET)
  transport = httpx.AsyncHTTPTransport(uds=socket_path)
  async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
    response = await client.request(
      method, "http://broker" + route, json=payload,
    )
    response.raise_for_status()
    value = response.json()
  if not isinstance(value, dict):
    raise ValueError("identity broker returned an invalid response")
  return value
