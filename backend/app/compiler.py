"""Compiles JSX source strings to ES modules using esbuild."""

import asyncio
import os
import tempfile
from pathlib import Path

from app.config import get_settings

_ESBUILD_TIMEOUT_SECS = 30


def _compiled_dir() -> Path:
  """Returns (and creates) the directory for compiled mini-app modules."""
  path = Path(get_settings().data_dir) / "compiled"
  path.mkdir(parents=True, exist_ok=True)
  return path


async def compile_jsx(app_id: int, jsx_source: str) -> str:
  """Compiles JSX source to an ES module and returns the output path.

  Args:
    app_id: The numeric ID of the mini-app being compiled.
    jsx_source: The JSX source code string.

  Returns:
    The absolute path of the compiled JS file.

  Raises:
    RuntimeError: If esbuild exits with a non-zero status.
  """
  out_path = _compiled_dir() / f"app-{app_id}.js"

  with tempfile.NamedTemporaryFile(
    suffix=".jsx", mode="w", delete=False, encoding="utf-8"
  ) as f:
    f.write(jsx_source)
    tmp_path = f.name

  try:
    try:
      proc = await asyncio.create_subprocess_exec(
        "esbuild",
        tmp_path,
        "--bundle",
        "--format=esm",
        "--jsx=automatic",
        "--platform=browser",
        "--external:react",
        "--external:react/jsx-runtime",
        "--external:react-dom",
        "--external:recharts",
        "--external:date-fns",
        f"--outfile={out_path}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
      )
    except FileNotFoundError:
      raise RuntimeError(
        "esbuild is not installed or not on PATH. "
        "The Docker image installs it automatically; for local dev run: "
        "npm install -g esbuild"
      )
    try:
      _, stderr = await asyncio.wait_for(
        proc.communicate(), timeout=_ESBUILD_TIMEOUT_SECS,
      )
    except asyncio.TimeoutError:
      proc.kill()
      await proc.communicate()
      raise RuntimeError(
        f"esbuild timed out after {_ESBUILD_TIMEOUT_SECS} seconds"
      )
    if proc.returncode != 0:
      raise RuntimeError(
        f"Compilation failed:\n{stderr.decode()}"
      )
  finally:
    os.unlink(tmp_path)

  return str(out_path)
