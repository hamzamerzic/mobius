#!/usr/bin/env python3
"""Select, review, and finalize an owner-approved Store update resolution."""

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request


def _post(path: str, payload: dict) -> dict:
  token = os.environ.get("AGENT_TOKEN")
  if not token:
    print("AGENT_TOKEN environment variable is not set.", file=sys.stderr)
    raise SystemExit(1)
  base = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
  request = urllib.request.Request(
    f"{base}/api/apps/{path}",
    data=json.dumps(payload).encode(),
    headers={
      "Authorization": f"Bearer {token}",
      "Content-Type": "application/json",
    },
    method="POST",
  )
  try:
    with urllib.request.urlopen(request, timeout=120) as response:
      return json.loads(response.read())
  except urllib.error.HTTPError as exc:
    body = exc.read().decode(errors="replace")
    try:
      detail = json.loads(body).get("detail", body)
    except json.JSONDecodeError:
      detail = body
    rendered = (
      json.dumps(detail, ensure_ascii=False)
      if isinstance(detail, dict) else detail
    )
    print(f"App update resolution failed ({exc.code}): {rendered}", file=sys.stderr)
    raise SystemExit(1) from exc
  except urllib.error.URLError as exc:
    print(f"App update resolution failed: {exc.reason}", file=sys.stderr)
    raise SystemExit(1) from exc


def main() -> None:
  parser = argparse.ArgumentParser(
    description="Select, review, or finalize a pending Store app update.",
  )
  parser.add_argument("source_dir")
  action = parser.add_mutually_exclusive_group(required=True)
  action.add_argument(
    "--policy",
    choices=("preserve-local", "exact-upstream"),
  )
  action.add_argument("--review", action="store_true")
  action.add_argument("--finalize", action="store_true")
  parser.add_argument("--reviewed-tree")
  args = parser.parse_args()
  if args.reviewed_tree and not args.finalize:
    parser.error("--reviewed-tree is only valid with --finalize")

  try:
    source_dir = str(Path(args.source_dir).resolve(strict=True))
  except (OSError, RuntimeError) as exc:
    print(f"Cannot resolve app source directory: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc
  if not Path(source_dir).is_dir():
    print("App source path is not a directory.", file=sys.stderr)
    raise SystemExit(1)

  if args.policy:
    policy = {
      "preserve-local": "preserve_local",
      "exact-upstream": "accept_reviewed_upstream_exact",
    }[args.policy]
    result = _post(
      "resolve-update/policy",
      {"source_dir": source_dir, "policy": policy},
    )
    print(json.dumps(result, ensure_ascii=False))
    return

  if args.review:
    result = _post("resolve-update/review", {"source_dir": source_dir})
    print(f"upstream_commit={result['upstream_commit']}")
    print(f"tree_oid={result['tree_oid']}")
    print("--- complete resolved source diff ---")
    print(result["diff"], end="" if result["diff"].endswith("\n") else "\n")
    return

  payload = {"source_dir": source_dir}
  if args.reviewed_tree:
    payload["reviewed_tree_oid"] = args.reviewed_tree
  result = _post("resolve-update", payload)
  print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
  main()
