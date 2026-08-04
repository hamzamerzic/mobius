"""Shared admission for Mobius-owned JavaScript compilers."""

import asyncio

import pytest

from app.build_admission import acquire_build_lease, build_lease_path


def test_build_lease_serializes_independent_callers(tmp_path, monkeypatch):
  monkeypatch.setenv("DATA_DIR", str(tmp_path))

  first = acquire_build_lease(blocking=False)
  assert first is not None
  try:
    assert acquire_build_lease(blocking=False) is None
  finally:
    first.close()

  with acquire_build_lease(blocking=False) as second:
    assert second is not None

  assert build_lease_path() == tmp_path / "run" / "build.lock"


def test_build_lease_close_is_idempotent(tmp_path, monkeypatch):
  monkeypatch.setenv("DATA_DIR", str(tmp_path))
  lease = acquire_build_lease(blocking=False)
  assert lease is not None

  lease.close()
  lease.close()

  replacement = acquire_build_lease(blocking=False)
  assert replacement is not None
  replacement.close()


@pytest.mark.asyncio
async def test_compiler_cancellation_while_waiting_does_not_spawn(
  monkeypatch,
):
  from app import compiler

  monkeypatch.setattr(
    compiler, "acquire_build_lease", lambda *, blocking: None,
  )
  monkeypatch.setattr(compiler, "_BUILD_LEASE_RETRY_SECONDS", 0)

  async def unexpected_spawn(*_args, **_kwargs):
    pytest.fail("a compiler waiting for the lease must not spawn")

  monkeypatch.setattr(asyncio, "create_subprocess_exec", unexpected_spawn)
  task = asyncio.create_task(compiler._run_rolldown(["node"], cwd=None))
  await asyncio.sleep(0)
  task.cancel()

  with pytest.raises(asyncio.CancelledError):
    await task


@pytest.mark.asyncio
async def test_compiler_cancellation_releases_held_lease(monkeypatch):
  from app import compiler

  released = []

  class Lease:
    def close(self):
      released.append(True)

  class Process:
    returncode = None
    killed = False

    async def communicate(self):
      if self.killed:
        return b"", b""
      await asyncio.Event().wait()

    def kill(self):
      self.killed = True

  process = Process()
  monkeypatch.setattr(
    compiler, "acquire_build_lease", lambda *, blocking: Lease(),
  )

  async def spawn(*_args, **_kwargs):
    return process

  monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
  task = asyncio.create_task(compiler._run_rolldown(["node"], cwd=None))
  await asyncio.sleep(0)
  task.cancel()

  with pytest.raises(asyncio.CancelledError):
    await task

  assert process.killed is True
  assert released == [True]
