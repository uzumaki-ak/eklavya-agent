"""Regression tests for deadline and flight-leadership cleanup paths."""

import asyncio
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app import worker
from app.core.exceptions import FlightLeadershipLost
from app.pipeline import persistence, runner
from app.schemas.artifact import RunArtifact
from tests.factories import draft, review_dict


def _ctx(seconds: float = 1.0) -> runner.JobContext:
    return runner.JobContext(
        uuid.uuid4(), "worker-1", 1, "digest", "user-1", 4, "Types of angles",
        time.monotonic() + seconds,
    )


async def test_whole_dispatch_deadline_terminalizes_run(monkeypatch):
    async def never_finishes(_ctx):
        await asyncio.sleep(60)

    persist_failure = AsyncMock()
    monkeypatch.setattr(runner, "_dispatch", never_finishes)
    monkeypatch.setattr(runner, "persist_failure", persist_failure)

    await runner._dispatch_before_deadline(_ctx(0.01))

    persist_failure.assert_awaited_once()
    assert persist_failure.await_args.args[1:] == (
        "generator_error", "pipeline_deadline_exceeded",
    )


async def test_flight_loss_cancels_only_graph_and_releases_run(monkeypatch):
    graph_started = asyncio.Event()

    async def graph(*_args):
        graph_started.set()
        await asyncio.sleep(60)

    async def lose_leadership(*_args):
        await graph_started.wait()
        raise FlightLeadershipLost("digest")

    persist_failure = AsyncMock()
    monkeypatch.setattr(runner, "execute_graph", graph)
    monkeypatch.setattr(runner.single_flight, "renew_leadership", lose_leadership)
    monkeypatch.setattr(runner, "persist_failure", persist_failure)
    monkeypatch.setattr(runner, "persist_result", AsyncMock())

    await runner._lead(_ctx(), token=7)

    persist_failure.assert_awaited_once()
    assert persist_failure.await_args.args[1:] == (
        "generator_error", "flight_leadership_lost",
    )


async def test_queue_retry_force_reclaims_stale_db_lease(monkeypatch):
    run_job = AsyncMock()
    monkeypatch.setattr(worker, "run_job", run_job)
    job = SimpleNamespace(attempts=2, update=AsyncMock())
    run_id = uuid.uuid4()

    await worker.run_pipeline({"job": job}, run_id=str(run_id))

    run_job.assert_awaited_once_with(run_id, worker.WORKER_ID, force_reclaim=True)


class _Session:
    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


async def test_not_leader_rolls_back_then_terminalizes_without_cache(monkeypatch):
    session = _Session()
    monkeypatch.setattr(persistence, "SessionLocal", lambda: session)
    monkeypatch.setattr(persistence.runs, "write_stage", AsyncMock())
    monkeypatch.setattr(persistence.flights, "complete_flight", AsyncMock(return_value=False))
    monkeypatch.setattr(persistence, "set_cached", AsyncMock())
    persist_failure = AsyncMock()
    monkeypatch.setattr(persistence, "persist_failure", persist_failure)

    await persistence.persist_result(_ctx(), 7, {})

    persistence.set_cached.assert_not_awaited()
    persist_failure.assert_awaited_once()
    assert persist_failure.await_args.args[1:] == (
        "generator_error", "flight_leadership_lost",
    )


async def test_runner_failure_recovers_the_complete_checkpointed_trail(monkeypatch):
    """A cancelled graph must not become an empty-attempt audit artifact."""
    envelope = {
        "drafts": [draft(text="Draft 1"), draft(text="Draft 2")],
        "reviews": [review_dict(passed=False)],
        "tags": None,
        "refinement_count": 1,
    }
    run = SimpleNamespace(
        progress_envelope=envelope,
        schema_repair_attempts=1,
        transport_attempts_total=2,
        logical_llm_calls=3,
        moderation_results={"draft_1": {"outcome": "clear"}},
    )
    session = _Session()
    write_stage = AsyncMock()
    monkeypatch.setattr(persistence, "SessionLocal", lambda: session)
    monkeypatch.setattr(persistence.runs, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(persistence.runs, "write_stage", write_stage)

    await persistence.persist_failure(
        _ctx(), "generator_error", "pipeline_deadline_exceeded"
    )

    fields = write_stage.await_args.kwargs
    artifact = RunArtifact.model_validate(fields["run_artifact"])
    assert [attempt.draft.explanation.text for attempt in artifact.attempts] == [
        "Draft 1", "Draft 2"
    ]
    assert artifact.attempts[-1].review is None
    assert artifact.provenance.logical_llm_calls == 3
    assert artifact.provenance.schema_repair_attempts == 1
    assert artifact.provenance.transport_attempts_total == 2
    assert fields["progress_envelope"] is None
