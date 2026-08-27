"""Terminal writes for a finished job.

The run's final state and the flight publication go in ONE transaction — a
'done' flight must never become visible before the result it points at is
durable. Redis is only written after that transaction commits.
"""

import asyncio
import contextlib
import logging
from datetime import datetime, timezone

from app.core.exceptions import LeaseLost
from app.db import flights, runs
from app.db.session import SessionLocal
from app.services.cache import set_cached
from app.services.envelope import cacheable, envelope_from_state, final_status

logger = logging.getLogger(__name__)

CLEANUP_TIMEOUT_SECONDS = 30


class NotLeader(Exception):
    """Flight leadership was lost during the final transaction."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
                            **envelope,
                            refinement_count=state.get("refinement_count", 0),
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
    so a waiting follower stops waiting and can take over."""
    with contextlib.suppress(asyncio.TimeoutError, TimeoutError, LeaseLost):
        async with asyncio.timeout(CLEANUP_TIMEOUT_SECONDS):
            async with SessionLocal() as session:
                async with session.begin():
                    await runs.write_stage(
                        session, ctx.run_id, ctx.worker, ctx.epoch,
                        status=stage, error_code=code,
                        current_stage="failed", completed_at=_utcnow(), lease_owner=None,
                    )
                    if token is not None:
                        await flights.complete_flight(
                            session, ctx.digest, ctx.run_id, token, success=False
                        )


async def persist_reused(ctx, envelope: dict, status: str) -> None:
    """Persist a cache hit / reused leader result onto this run."""
    with contextlib.suppress(LeaseLost):
        async with SessionLocal() as session:
            async with session.begin():
                await runs.write_stage(
                    session, ctx.run_id, ctx.worker, ctx.epoch,
                    status=status, cache_hit=True, current_stage="done",
                    completed_at=_utcnow(), lease_owner=None, **envelope,
                )
