"""Position is always server-assigned on create (Defect 1, Option A) and a
DB uniqueness violation surfaces as 409, not 500 (Defect 2.2).

Background: the create path used to honour a client-supplied ``position > 0``
literally. The FE sends 0-based array indices, so index 0 fell through to
auto-append but index >= 1 was taken literally and collided with an existing
live row on the ``uq_*_position_live`` partial-unique index -> IntegrityError
-> unhandled 500. Create now ALWAYS appends; the IntegrityError handler is the
safety net for genuine concurrent-append races.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.middleware.error_handler import register_exception_handlers
from app.schemas.task import TaskCreateRequest
from app.services.task_service import TaskService


IST = timezone(timedelta(hours=5, minutes=30))
START = datetime(2026, 5, 1, tzinfo=IST)
END = datetime(2026, 6, 1, tzinfo=IST)


def _task_svc_for_create(monkeypatch, *, next_position: int) -> TaskService:
    """TaskService wired so create() runs in-process without a DB."""
    svc = TaskService(MagicMock())
    activity = MagicMock()
    activity.id = "act1"
    activity.project_id = "p1"
    activity.start_date = START
    project = MagicMock()
    project.status = "published"
    project.start_date = START
    svc.activities.get_by_id = MagicMock(return_value=activity)
    svc.projects.get_by_id = MagicMock(return_value=project)
    svc.repo = MagicMock()
    svc.repo.next_position_for_activity.return_value = next_position
    row = MagicMock()
    row.id = "t1"
    row.project_id = "p1"
    row.activity_id = "act1"
    row.name = "T1"
    svc.repo.create.return_value = row
    svc.audit = MagicMock()
    svc.comments = MagicMock()
    svc._validate_priority = MagicMock()
    svc._cascade_revert_from_new_child = MagicMock()
    monkeypatch.setattr(
        "app.services.task_service.assert_task_subtask_writable", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.task_service.validate_entity_dates", lambda *a, **k: None,
    )
    return svc


def _payload(**over) -> TaskCreateRequest:
    base = dict(name="T1", start_date=START, end_date=END)
    base.update(over)
    return TaskCreateRequest(**base)


def test_create_ignores_explicit_position_and_appends(monkeypatch):
    """An explicit (colliding) client position is ignored; create appends."""
    svc = _task_svc_for_create(monkeypatch, next_position=13)
    svc.create("act1", _payload(position=1), caller_user_id="u1")
    svc.repo.next_position_for_activity.assert_called_once_with("act1")
    assert svc.repo.create.call_args.kwargs["position"] == 13


def test_create_without_position_appends(monkeypatch):
    """Omitting position behaves identically — always auto-append."""
    svc = _task_svc_for_create(monkeypatch, next_position=13)
    svc.create("act1", _payload(), caller_user_id="u1")
    assert svc.repo.create.call_args.kwargs["position"] == 13


def test_integrity_error_maps_to_409():
    """A DB IntegrityError surfaces as a clean 409 envelope, not a 500."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/projects/boom")
    def boom():
        raise IntegrityError(
            "INSERT ...", {}, Exception("duplicate key value violates unique constraint"),
        )

    resp = TestClient(app, raise_server_exceptions=False).get("/projects/boom")
    assert resp.status_code == 409
    body = resp.json()
    assert body["status"] == 409
    assert body["error"]["errorIdentifier"] == "conflict"


def test_integrity_error_titlecase_on_task_path():
    """M/A/T/S paths keep monolith TitleCase identifier (ConflictError)."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/activities/{aid}/tasks/create")
    def boom(aid: str):
        raise IntegrityError("INSERT ...", {}, Exception("dup"))

    resp = TestClient(app, raise_server_exceptions=False).post(
        "/activities/a1/tasks/create",
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["errorIdentifier"] == "ConflictError"
