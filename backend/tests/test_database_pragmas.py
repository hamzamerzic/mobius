"""SQLite connections install their lock handler before lock-taking pragmas."""

from types import SimpleNamespace

import pytest

from app import database


def _capture_connect_pragmas(monkeypatch, tmp_path):
  """Run _make_engine with a fake engine and return the pragmas a new
  connection executes."""
  listeners = {}

  def _listens_for(_engine, event_name):
    def _register(callback):
      listeners[event_name] = callback
      return callback

    return _register

  class _Cursor:
    def __init__(self):
      self.statements = []

    def execute(self, statement):
      self.statements.append(statement)

    def close(self):
      return None

  class _Connection:
    def __init__(self):
      self.connection_cursor = _Cursor()

    def cursor(self):
      return self.connection_cursor

  monkeypatch.setattr(database.event, "listens_for", _listens_for)
  monkeypatch.setattr(database, "create_engine", lambda *_a, **_k: object())
  monkeypatch.setattr(
    database,
    "get_settings",
    lambda: SimpleNamespace(
      database_url=f"sqlite:///{tmp_path / 'pragma.db'}",
    ),
  )

  database._make_engine()
  connection = _Connection()
  listeners["connect"](connection, object())
  return connection.connection_cursor.statements


def test_sqlite_connection_pragma_order(monkeypatch, tmp_path):
  assert _capture_connect_pragmas(monkeypatch, tmp_path) == [
    "PRAGMA busy_timeout=5000",
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=FULL",
    f"PRAGMA journal_size_limit={database._WAL_SIZE_LIMIT_BYTES}",
  ]


def test_wal_size_limit_is_set_so_the_journal_cannot_ratchet_unbounded(
  monkeypatch, tmp_path
):
  """SQLite defaults journal_size_limit to -1, which never truncates the WAL:
  a checkpoint returns pages to the database but leaves the file at its
  high-water mark. Left unset it reached 1.9 GB holding 3.5 MB of live pages.
  Every connection must declare a limit for a checkpoint to reclaim the file."""
  statements = _capture_connect_pragmas(monkeypatch, tmp_path)

  limits = [s for s in statements if "journal_size_limit" in s]
  assert limits == [f"PRAGMA journal_size_limit={database._WAL_SIZE_LIMIT_BYTES}"]
  assert database._WAL_SIZE_LIMIT_BYTES > 0


@pytest.mark.parametrize("pragma", ["journal_mode=WAL", "busy_timeout=5000"])
def test_wal_size_limit_follows_the_pragmas_it_depends_on(
  monkeypatch, tmp_path, pragma
):
  """journal_size_limit only means anything in WAL mode, and the busy handler
  must already be installed before any pragma that can contend for a lock."""
  statements = _capture_connect_pragmas(monkeypatch, tmp_path)

  assert statements.index(f"PRAGMA {pragma}") < statements.index(
    f"PRAGMA journal_size_limit={database._WAL_SIZE_LIMIT_BYTES}"
  )
