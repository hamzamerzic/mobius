# backend/tests/conftest.py

# Set env vars BEFORE any app imports so that get_settings() lru_cache
# picks up the test values on first call.
import os
os.environ["SECRET_KEY"] = "test-secret-key-exactly-32-chars!!"
os.environ["DATABASE_URL"] = "sqlite:////tmp/mobius_test/test.db"
os.environ["DATA_DIR"] = "/tmp/mobius_test"
os.environ["FRONTEND_ORIGIN"] = "http://localhost:5173"

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app import models
from app.auth import create_access_token, hash_password


# Use the same engine the app imported (which used our env vars above).
from app.database import engine as _app_engine, SessionLocal as _SessionLocal


@pytest.fixture(autouse=True)
def reset_db(reset_data_dir):
  """Drop and recreate all tables before each test for isolation."""
  # Dispose the connection pool so SQLAlchemy opens a fresh connection to
  # the recreated data dir, rather than reusing the deleted file's handle.
  _app_engine.dispose()
  Base.metadata.drop_all(bind=_app_engine)
  Base.metadata.create_all(bind=_app_engine)
  yield
  Base.metadata.drop_all(bind=_app_engine)


@pytest.fixture(autouse=True)
def reset_data_dir():
  """Wipe and recreate the test data dir before each test."""
  p = Path(os.environ["DATA_DIR"])
  if p.exists():
    shutil.rmtree(p)
  p.mkdir(parents=True)
  yield
  if p.exists():
    shutil.rmtree(p)


@pytest.fixture
def db(reset_db):
  """Returns a live DB session with an owner pre-created."""
  session = _SessionLocal()
  owner = models.Owner(
    username="test",
    hashed_password=hash_password("password"),
  )
  session.add(owner)
  session.commit()
  session.refresh(owner)
  yield session
  session.close()


@pytest.fixture
def client(db):
  """Returns a TestClient with get_db overridden to use the test session."""
  def override_db():
    yield db

  app.dependency_overrides[get_db] = override_db
  # Clear lru_cache so DATA_DIR env var is re-read for this test.
  get_settings.cache_clear()
  with TestClient(app) as c:
    yield c
  app.dependency_overrides.clear()
  get_settings.cache_clear()


@pytest.fixture
def auth(db):
  """Returns Authorization headers for the test owner."""
  token = create_access_token({"sub": "test"})
  return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def chat(db):
  """Returns a pre-created chat row."""
  c = models.Chat(id="testchat", title="Test chat", messages=[])
  db.add(c)
  db.commit()
  db.refresh(c)
  yield c
