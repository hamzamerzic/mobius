#!/usr/bin/env python3
"""Soft-delete one exact app id and print its durable recovery receipt."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description=(
      "Soft-delete one numeric app id after partner confirmation and retain "
      "the exact recovery handle."
    ),
  )
  parser.add_argument("app_id", type=int)
  parser.add_argument(
    "--confirm",
    action="store_true",
    help="required acknowledgement that the partner confirmed this deletion",
  )
  args = parser.parse_args()
  if not args.confirm:
    parser.error("--confirm is required after the partner confirms deletion")
  return args


def _request(url: str, token: str, *, method: str = "GET") -> bytes:
  request = urllib.request.Request(
    url,
    headers={"Authorization": f"Bearer {token}"},
    method=method,
  )
  try:
    with urllib.request.urlopen(request, timeout=120) as response:
      return response.read()
  except urllib.error.HTTPError as exc:
    body = exc.read().decode(errors="replace")
    try:
      detail = json.loads(body).get("detail", body)
    except json.JSONDecodeError:
      detail = body
    raise RuntimeError(
      f"App delete failed ({exc.code}): "
      f"{json.dumps(detail, ensure_ascii=False) if isinstance(detail, dict) else detail}"
    ) from exc
  except urllib.error.URLError as exc:
    raise RuntimeError(f"App delete failed: {exc.reason}") from exc


def main() -> None:
  args = _args()
  token = os.environ.get("AGENT_TOKEN")
  if not token:
    print("AGENT_TOKEN environment variable is not set.", file=sys.stderr)
    raise SystemExit(1)
  base = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
  url = f"{base}/api/apps/{args.app_id}"
  try:
    app = json.loads(_request(url, token))
    if not isinstance(app, dict) or app.get("id") != args.app_id:
      raise RuntimeError("App lookup did not return the requested numeric id.")
    _request(url, token, method="DELETE")
  except (json.JSONDecodeError, RuntimeError) as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1) from exc
  receipt = {
    "status": "deleted",
    "app_id": app["id"],
    "name": app.get("name"),
    "slug": app.get("slug"),
    "source_dir": app.get("source_dir"),
    "recover_path": f"/api/apps/{app['id']}/recover",
    "recoverable_for_days": 7,
  }
  print(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
  main()
