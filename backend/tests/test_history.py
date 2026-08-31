"""GET /history — user isolation, and surviving pre-Part-2 rows.

An endpoint whose whole job is returning stored history must not 500 on history
it cannot represent, so legacy rows are filtered and counted rather than parsed.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import pipeline as pipeline_route
from app.api.routes.deps import resolve_user_id
from app.db import history
from app.pipeline.artifact import build_artifact, meta_for_run
from app.services.submission import _request_hash
from tests.factories import draft, review_dict, tags

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _approved_artifact() -> dict:
    envelope = {
        "drafts": [draft()],
        "reviews": [review_dict(passed=True)],
        "tags": tags().model_dump(),
        "refinement_count": 0,
    }
    meta = meta_for_run(
        run_id="run-1", user_id="user-1", grade=5, topic="The solar system",
        started_at=NOW, pipeline_status="completed_pass",
    )
    return build_artifact(envelope, meta).model_dump(mode="json", by_alias=True)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self._rows

    def scalar_one(self):
        return self._rows[0]


class _RecordingSession:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.rows)


async def test_history_query_keeps_valid_artifacts_across_schema_versions():
    session = _RecordingSession([])
    await history.list_artifacts(session, "user-1")

    sql = str(session.statements[0])
    assert "generation_runs.user_id = " in sql
    assert "run_artifact IS NOT NULL" in sql
    assert "schema_version" not in sql


async def test_legacy_count_includes_null_version_terminal_rows():
    session = _RecordingSession([2])
    count = await history.count_legacy(session, "user-1")

    sql = str(session.statements[0])
    assert count == 2
    assert "run_artifact IS NULL" in sql
    assert "generation_runs.status IN" in sql
    assert "schema_version" not in sql


async def test_history_returns_stored_artifacts(monkeypatch):
    stored = _approved_artifact()

    async def _list(*_args, **_kwargs):
        return [stored]

    async def _legacy(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(pipeline_route.history, "list_artifacts", _list)
    monkeypatch.setattr(pipeline_route.history, "count_legacy", _legacy)

    response = await pipeline_route.get_history(user_id="user-1", limit=20, offset=0, session=None)
    assert response.count == 1
    assert response.artifacts[0].final.status == "approved"


async def test_legacy_rows_are_reported_not_crashed(monkeypatch):
    """A pre-Part-2 row must not turn the whole listing into a 500."""

    async def _list(*_args, **_kwargs):
        return [{"run_id": "old", "attempts": "not-an-artifact"}]

    async def _legacy(*_args, **_kwargs):
        return 3

    monkeypatch.setattr(pipeline_route.history, "list_artifacts", _list)
    monkeypatch.setattr(pipeline_route.history, "count_legacy", _legacy)

    response = await pipeline_route.get_history(user_id="user-1", limit=20, offset=0, session=None)
    assert response.count == 0
    assert response.legacy_excluded == 4  # 3 filtered by SQL, 1 unparsable


def test_history_user_id_is_pattern_validated():
    """The constraint must survive onto the query parameter itself.

    Written as a schema assertion because the bug it guards was invisible from
    the code: with a bare `user_id: UserId = Query(...)` default, FastAPI builds
    the field from the Query alone and drops the type's StringConstraints, so
    `?user_id=bad user` was accepted with a 200.
    """
    from app.main import app

    parameters = app.openapi()["paths"]["/history"]["get"]["parameters"]
    user_id = next(p for p in parameters if p["name"] == "user_id")

    assert user_id["required"] is True
    assert "pattern" in user_id["schema"], "the user_id constraint was dropped"
    assert user_id["schema"]["maxLength"] == 128


def test_header_user_id_uses_the_same_validation_as_body_and_history():
    request = SimpleNamespace(headers={"x-user-id": "bad user"}, client=None)
    with pytest.raises(HTTPException) as exc_info:
        resolve_user_id(request, None)
    assert exc_info.value.status_code == 422


def test_idempotency_hash_is_bound_to_the_user():
    first = _request_hash("user-1", 5, "fractions")
    second = _request_hash("user-2", 5, "fractions")
    assert first != second
