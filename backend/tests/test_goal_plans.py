"""Durable Goal-plan validation, ordering, progress, and route contracts."""

from datetime import timedelta
import importlib.util
from pathlib import Path

import pytest

from app import auth as auth_mod, models
from app import broadcast as broadcast_mod


def _goal_plan_script():
  path = Path(__file__).resolve().parents[1] / "scripts" / "goal_plan.py"
  spec = importlib.util.spec_from_file_location("goal_plan_script", path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def _active_goal(client, owner_token, db):
  auth = {"Authorization": f"Bearer {owner_token}"}
  response = client.post("/api/chats", json={"title": "Planned goal"}, headers=auth)
  assert response.status_code == 200, response.text
  chat_id = response.json()["id"]
  db.add(models.ChatRun(
    id="goal-root",
    root_run_id="goal-root",
    chat_id=chat_id,
    status="running",
    provider="codex",
    goal_objective="Ship the release",
  ))
  db.commit()
  return auth, chat_id


def _agent_run_auth(db, chat_id, run_id):
  owner = db.query(models.Owner).first()
  token = auth_mod.create_agent_token(
    chat_id,
    run_id,
    owner.username,
    owner.token_epoch,
    expires_delta=timedelta(minutes=5),
  )
  return {"Authorization": f"Bearer {token}"}


def test_current_turn_promotes_atomically_without_a_goal_message(
  client, owner_token, db,
):
  owner_auth = {"Authorization": f"Bearer {owner_token}"}
  created = client.post("/api/chats", json={"title": "Ordinary"}, headers=owner_auth)
  chat_id = created.json()["id"]
  db.add(models.ChatRun(
    id="ordinary-run",
    root_run_id="ordinary-run",
    chat_id=chat_id,
    status="running",
    provider="codex",
  ))
  db.commit()
  agent_auth = _agent_run_auth(db, chat_id, "ordinary-run")

  broadcast = broadcast_mod.create_broadcast(chat_id)
  try:
    promoted = client.post(
      f"/api/chats/{chat_id}/goal",
      json={"objective": "Repair every defect and verify the suite"},
      headers=agent_auth,
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json() == {
      "objective": "Repair every defect and verify the suite",
      "root_run_id": "ordinary-run",
      "run_id": "ordinary-run",
      "state": "promoted",
    }
    assert [
      event["type"] for event in broadcast.event_log
    ] == ["goal_activated"]
    db.expire_all()
    run = db.query(models.ChatRun).filter(models.ChatRun.id == "ordinary-run").one()
    assert run.goal_objective == "Repair every defect and verify the suite"
    chat = db.query(models.Chat).filter(models.Chat.id == chat_id).one()
    assert all(
      "/goal" not in str(message.get("content", ""))
      for message in chat.messages
    )

    retry = client.post(
      f"/api/chats/{chat_id}/goal",
      json={"objective": "Repair every defect and verify the suite"},
      headers=agent_auth,
    )
    assert retry.status_code == 200
    assert retry.json()["state"] == "active"
    assert [
      event["type"] for event in broadcast.event_log
    ] == ["goal_activated"]
    conflict = client.post(
      f"/api/chats/{chat_id}/goal",
      json={"objective": "Do something else"},
      headers=agent_auth,
    )
    assert conflict.status_code == 409

    plan = client.put(
      f"/api/chats/{chat_id}/goal-plan",
      json={
        "expected_revision": 0,
        "tasks": [{"id": "repair", "title": "Repair every defect"}],
      },
      headers=agent_auth,
    )
    assert plan.status_code == 200, plan.text
    assert (
      plan.json()["plan"]["objective"]
      == "Repair every defect and verify the suite"
    )
  finally:
    broadcast_mod.remove_broadcast(chat_id)


def test_goal_promotion_rejects_browser_wrong_chat_and_terminal_run_tokens(
  client, owner_token, db,
):
  owner_auth = {"Authorization": f"Bearer {owner_token}"}
  first = client.post("/api/chats", json={"title": "First"}, headers=owner_auth).json()
  second = client.post("/api/chats", json={"title": "Second"}, headers=owner_auth).json()
  db.add_all([
    models.ChatRun(
      id="live-run", root_run_id="live-run", chat_id=first["id"],
      status="running", provider="claude",
    ),
    models.ChatRun(
      id="settled-run", root_run_id="settled-run", chat_id=first["id"],
      status="completed", provider="claude",
    ),
  ])
  db.commit()
  agent_auth = _agent_run_auth(db, first["id"], "live-run")
  settled_auth = _agent_run_auth(db, first["id"], "settled-run")

  browser = client.post(
    f"/api/chats/{first['id']}/goal",
    json={"objective": "Not allowed"}, headers=owner_auth,
  )
  assert browser.status_code == 403
  wrong_chat = client.post(
    f"/api/chats/{second['id']}/goal",
    json={"objective": "Not allowed"}, headers=agent_auth,
  )
  assert wrong_chat.status_code == 403
  terminal = client.post(
    f"/api/chats/{first['id']}/goal",
    json={"objective": "Too late"}, headers=settled_auth,
  )
  assert terminal.status_code == 401
  assert "no longer active" in terminal.json()["detail"]


def test_promotion_of_a_continuation_stamps_its_logical_root(
  client, owner_token, db,
):
  owner_auth = {"Authorization": f"Bearer {owner_token}"}
  chat_id = client.post(
    "/api/chats", json={"title": "Continued"}, headers=owner_auth,
  ).json()["id"]
  db.add_all([
    models.ChatRun(
      id="logical-root", root_run_id="logical-root", chat_id=chat_id,
      status="interrupted", provider="claude",
    ),
    models.ChatRun(
      id="physical-resume", root_run_id="logical-root", chat_id=chat_id,
      status="running", provider="claude",
    ),
  ])
  db.commit()

  promoted = client.post(
    f"/api/chats/{chat_id}/goal",
    json={"objective": "Finish the resumed migration"},
    headers=_agent_run_auth(db, chat_id, "physical-resume"),
  )

  assert promoted.status_code == 200, promoted.text
  assert promoted.json()["root_run_id"] == "logical-root"
  db.expire_all()
  roots = {
    row.id: row.goal_objective
    for row in db.query(models.ChatRun).filter(models.ChatRun.chat_id == chat_id)
  }
  assert roots == {
    "logical-root": "Finish the resumed migration",
    "physical-resume": "Finish the resumed migration",
  }


def test_goal_promotion_commit_failure_is_loud_and_atomic(
  client, owner_token, db, monkeypatch,
):
  from app import chat_writer

  owner_auth = {"Authorization": f"Bearer {owner_token}"}
  chat_id = client.post(
    "/api/chats", json={"title": "Atomic failure"}, headers=owner_auth,
  ).json()["id"]
  db.add(models.ChatRun(
    id="failing-run", root_run_id="failing-run", chat_id=chat_id,
    status="running", provider="codex",
  ))
  db.commit()

  def fail_commit(session):
    session.rollback()
    return False

  monkeypatch.setattr(chat_writer, "_commit_or_rollback", fail_commit)
  with pytest.raises(chat_writer._PersistFailed, match="PromoteRunToGoal"):
    chat_writer.get_writer()._promote_run_to_goal(
      db,
      chat_writer.PromoteRunToGoal(
        chat_id=chat_id,
        run_token="failing-run",
        objective="Persist all-or-nothing",
      ),
    )

  db.expire_all()
  run = db.query(models.ChatRun).filter(models.ChatRun.id == "failing-run").one()
  assert run.goal_objective is None


def test_parallel_roots_release_dependent_task_only_after_all_complete(
  client, owner_token, db,
):
  auth, chat_id = _active_goal(client, owner_token, db)
  tasks = [
    {"id": "a", "title": "Run A", "depends_on": []},
    {"id": "b", "title": "Run B", "depends_on": []},
    {"id": "c", "title": "Run C", "depends_on": ["a", "b"]},
  ]
  created = client.put(
    f"/api/chats/{chat_id}/goal-plan",
    json={"expected_revision": 0, "tasks": tasks}, headers=auth,
  )
  assert created.status_code == 200, created.text
  plan = created.json()["plan"]
  assert plan["revision"] == 1
  assert plan["summary"] == {
    "completed": 0,
    "total": 3,
    "running": [],
    "ready": ["a", "b"],
    "can_complete": False,
    "completion_blockers": ["a", "b", "c"],
  }

  a_running = client.patch(
    f"/api/chats/{chat_id}/goal-plan/tasks/a",
    json={"expected_revision": 1, "status": "running"}, headers=auth,
  )
  assert a_running.status_code == 200, a_running.text
  assert a_running.json()["plan"]["summary"]["running"] == ["a"]

  premature = client.patch(
    f"/api/chats/{chat_id}/goal-plan/tasks/c",
    json={"expected_revision": 2, "status": "running"}, headers=auth,
  )
  assert premature.status_code == 422
  assert "dependencies complete" in premature.json()["detail"]

  revision = 2
  for task_id, status in (
    ("a", "completed"),
    ("b", "running"),
    ("b", "completed"),
    ("c", "running"),
  ):
    response = client.patch(
      f"/api/chats/{chat_id}/goal-plan/tasks/{task_id}",
      json={"expected_revision": revision, "status": status}, headers=auth,
    )
    assert response.status_code == 200, response.text
    revision += 1
  final = response.json()["plan"]
  assert final["summary"]["running"] == ["c"]
  assert final["summary"]["completed"] == 2
  assert final["summary"]["can_complete"] is False
  assert final["summary"]["completion_blockers"] == ["c"]


def test_repeated_task_needs_full_progress_and_stale_revision_cannot_overwrite(
  client, owner_token, db,
):
  auth, chat_id = _active_goal(client, owner_token, db)
  created = client.put(
    f"/api/chats/{chat_id}/goal-plan",
    json={
      "expected_revision": 0,
      "tasks": [{
        "id": "repeat",
        "title": "Run the audit three times",
        "status": "running",
        "depends_on": [],
        "progress": {"current": 0, "total": 3},
      }],
    },
    headers=auth,
  )
  assert created.status_code == 200, created.text

  partial = client.patch(
    f"/api/chats/{chat_id}/goal-plan/tasks/repeat",
    json={"expected_revision": 1, "progress": {"current": 2, "total": 3}},
    headers=auth,
  )
  assert partial.status_code == 200, partial.text
  not_done = client.patch(
    f"/api/chats/{chat_id}/goal-plan/tasks/repeat",
    json={"expected_revision": 2, "status": "completed"}, headers=auth,
  )
  assert not_done.status_code == 422
  assert "repeated progress is full" in not_done.json()["detail"]

  stale = client.patch(
    f"/api/chats/{chat_id}/goal-plan/tasks/repeat",
    json={"expected_revision": 1, "note": "stale writer"}, headers=auth,
  )
  assert stale.status_code == 409

  full = client.patch(
    f"/api/chats/{chat_id}/goal-plan/tasks/repeat",
    json={"expected_revision": 2, "progress": {"current": 3, "total": 3}},
    headers=auth,
  )
  assert full.status_code == 200, full.text
  completed = client.patch(
    f"/api/chats/{chat_id}/goal-plan/tasks/repeat",
    json={"expected_revision": 3, "status": "completed"}, headers=auth,
  )
  assert completed.status_code == 200, completed.text
  assert completed.json()["plan"]["summary"]["completed"] == 1
  assert completed.json()["plan"]["summary"]["can_complete"] is True
  assert completed.json()["plan"]["summary"]["completion_blockers"] == []


def test_cancelled_work_is_removed_from_the_completion_route(
  client, owner_token, db,
):
  auth, chat_id = _active_goal(client, owner_token, db)
  created = client.put(
    f"/api/chats/{chat_id}/goal-plan",
    json={
      "expected_revision": 0,
      "tasks": [
        {"id": "done", "title": "Required work", "status": "completed"},
        {"id": "removed", "title": "No longer needed", "status": "cancelled"},
      ],
    },
    headers=auth,
  )
  assert created.status_code == 200, created.text
  summary = created.json()["plan"]["summary"]
  assert summary["can_complete"] is True
  assert summary["completion_blockers"] == []


def test_completion_preflight_names_only_unfinished_required_work():
  helper = _goal_plan_script()
  plan = {
    "tasks": [
      {"id": "done", "title": "Finished", "status": "completed"},
      {"id": "removed", "title": "Removed", "status": "cancelled"},
      {"id": "next", "title": "Run final audit", "status": "pending"},
      {"id": "blocked", "title": "Resolve blocker", "status": "blocked"},
    ],
  }
  assert helper._completion_blockers(None) == []
  assert helper._completion_blockers(plan) == [
    "Run final audit", "Resolve blocker",
  ]


def test_plan_rejects_cycles_missing_dependencies_and_non_goal_runs(
  client, owner_token, db,
):
  auth, chat_id = _active_goal(client, owner_token, db)
  cycle = client.put(
    f"/api/chats/{chat_id}/goal-plan",
    json={
      "expected_revision": 0,
      "tasks": [
        {"id": "a", "title": "A", "depends_on": ["b"]},
        {"id": "b", "title": "B", "depends_on": ["a"]},
      ],
    }, headers=auth,
  )
  assert cycle.status_code == 422
  assert "cycle" in cycle.json()["detail"]

  missing = client.put(
    f"/api/chats/{chat_id}/goal-plan",
    json={
      "expected_revision": 0,
      "tasks": [{"id": "a", "title": "A", "depends_on": ["gone"]}],
    }, headers=auth,
  )
  assert missing.status_code == 422
  assert "missing task" in missing.json()["detail"]

  db.query(models.ChatRun).filter(models.ChatRun.id == "goal-root").update({
    models.ChatRun.status: "completed",
  })
  db.commit()
  inactive = client.get(f"/api/chats/{chat_id}/goal-plan", headers=auth)
  assert inactive.status_code == 200
  assert inactive.json() == {"plan": None}
  rejected = client.put(
    f"/api/chats/{chat_id}/goal-plan",
    json={"expected_revision": 0, "tasks": [{"id": "a", "title": "A"}]},
    headers=auth,
  )
  assert rejected.status_code == 409
