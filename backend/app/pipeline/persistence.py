"""Terminal writes for a finished job.

The run's final state and the flight publication go in ONE transaction — a
'done' flight must never become visible before the result it points at is
durable. Redis is only written after that transaction commits.

Every path here writes the RunArtifact and the summary columns from the same
envelope, in one call, so the two can never describe different runs.
"""

import asyncio
import contextlib
import logging
from datetime import datetime, timezone

from app.core.exceptions import LeaseLost
from app.db import flights, runs
from app.db.session import SessionLocal
from app.pipeline.artifact import artifact_json, build_artifact, meta_for_run
from app.services.cache import set_cached
from app.services.envelope import (
    cacheable,
    envelope_from_state,
    final_status,
    summary_from_envelope,
)

logger = logging.getLogger(__name__)

CLEANUP_TIMEOUT_SECONDS = 30


class NotLeader(Exception):
    """Flight leadership was lost during the final transaction."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _columns(ctx, envelope: dict, status: str, state: dict | None, *, cache_hit: bool) -> dict:
    """The full set of content columns for one terminal write.

    Artifact and summary both come from `envelope`, which is the point: they are
    two projections of one value, not two values that have to be kept in step.
    """
    artifact = build_artifact(
        envelope,
        meta_for_run(
            run_id=str(ctx.run_id),
            user_id=ctx.user_id,
            grade=ctx.grade,
            topic=ctx.topic,
            started_at=ctx.started_at,
            pipeline_status=status,
            reason_code=(state or {}).get("error_code"),
            cache_hit=cache_hit,
            state=state,
        ),
    )
    return {
        **summary_from_envelope(envelope),
        "tags": envelope.get("tags"),
        "refinement_count": envelope.get("refinement_count", 0) or 0,
        "run_artifact": artifact_json(artifact),
        "progress_envelope": None,
    }


async def persist_result(ctx, token: int, state: dict) -> None:
    """Write the finished run, publish the flight, then cache — in that order."""
    status = final_status(state)
    envelope = envelope_from_state(state)
    leadership_lost = False
    committed = False

    with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
        async with asyncio.timeout(CLEANUP_TIMEOUT_SECONDS):
            try:
                async with SessionLocal() as session:
                    async with session.begin():
                        await runs.write_stage(
                            session, ctx.run_id, ctx.worker, ctx.epoch,
                            status=status,
                            **_columns(ctx, envelope, status, state, cache_hit=False),
                            schema_repair_attempts=state.get("schema_repair_attempts", 0),
                            transport_attempts_total=state.get("transport_attempts_total", 0),
                            logical_llm_calls=state.get("logical_llm_calls", 0),
                            moderation_results=state.get("moderation_results"),
                            error_code=state.get("error_code"),
                            current_stage="done",
                            completed_at=_utcnow(),
                            lease_owner=None,  # release
                        )
                        published = await flights.complete_flight(
                            session, ctx.digest, ctx.run_id, token, success=cacheable(status)
                        )
                        if not published:
                            raise NotLeader()
            except LeaseLost:
                logger.warning("run %s: lease lost before persist, discarding", ctx.run_id)
                return
            except NotLeader:
                logger.warning("run %s: flight leadership lost, not publishing", ctx.run_id)
                leadership_lost = True
            else:
                committed = True

            if committed:
                await set_cached(ctx.digest, envelope, status)

    if leadership_lost:
        # The atomic result/flight transaction was intentionally rolled back.
        # Finish our own run separately so it cannot remain "processing" forever.
        await persist_failure(ctx, "generator_error", "flight_leadership_lost")


async def persist_failure(ctx, stage: str, code: str, token: int | None = None) -> None:
    """Record a terminal failure. Never cached, and the flight is marked failed
    so a waiting follower stops waiting and can take over.

    An artifact is still written. The executor checkpoints the complete ordered
    envelope after every node, so this path recovers all completed drafts and
    reviews even after the in-memory graph state has been cancelled.
    """
    with contextlib.suppress(asyncio.TimeoutError, TimeoutError, LeaseLost):
        async with asyncio.timeout(CLEANUP_TIMEOUT_SECONDS):
            async with SessionLocal() as session:
                async with session.begin():
                    run = await runs.get_run(session, ctx.run_id)
                    envelope = (run.progress_envelope if run is not None else None) or {}
                    state = {
                        "error_code": code,
                        "schema_repair_attempts": getattr(
                            run, "schema_repair_attempts", 0
                        ),
                        "transport_attempts_total": getattr(
                            run, "transport_attempts_total", 0
                        ),
                        "logical_llm_calls": getattr(run, "logical_llm_calls", 0),
                        "moderation_results": getattr(run, "moderation_results", None),
                    }
                    await runs.write_stage(
                        session, ctx.run_id, ctx.worker, ctx.epoch,
                        status=stage, error_code=code,
                        **_columns(ctx, envelope, stage, state, cache_hit=False),
                        current_stage="failed", completed_at=_utcnow(), lease_owner=None,
                    )
                    if token is not None:
                        await flights.complete_flight(
                            session, ctx.digest, ctx.run_id, token, success=False
                        )


async def persist_reused(ctx, envelope: dict, status: str) -> None:
    """Persist a cache hit / reused leader result onto this run.

    The content is borrowed; the artifact is not. It is rebuilt with this run's
    own id, owner and timestamps and `cache_hit=True`, so the audit trail never
    claims this run did work it actually reused.
    """
    with contextlib.suppress(LeaseLost):
        async with SessionLocal() as session:
            async with session.begin():
                await runs.write_stage(
                    session, ctx.run_id, ctx.worker, ctx.epoch,
                    status=status, cache_hit=True, current_stage="done",
                    completed_at=_utcnow(), lease_owner=None,
                    **_columns(ctx, envelope, status, None, cache_hit=True),
                )
