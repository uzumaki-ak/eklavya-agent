"""Job entry point.

Ordering matters here:
  1. Claim the DB lease, then start the lease guard — everything after this,
     including cache lookup and follower waiting, is covered by it.
  2. One deadline for the WHOLE job, set before any waiting. A follower that
     waited 200s does not then get a fresh generation budget.
  3. Loop election/following until we either reuse a result or hold a real
     leadership token. Never generate without one.
"""

import asyncio
import contextlib
import logging
import time
import uuid

from app.core.config import settings
from app.core.exceptions import FlightLeadershipLost, LeaseLost, PipelineDeadlineExceeded
from app.db import runs
from app.db.session import SessionLocal
from app.pipeline import single_flight
from app.pipeline.executor import execute_graph
from app.pipeline.persistence import persist_failure, persist_result, persist_reused
from app.services.cache import get_cached
from app.services.lease import lease_guard

logger = logging.getLogger(__name__)

MAX_ELECTION_ROUNDS = 3  # bounded, so a flapping flight can't loop forever


class JobContext:
    """Everything one job needs, so helpers don't take eight positional args."""

    __slots__ = ("run_id", "worker", "epoch", "digest", "grade", "topic", "deadline")

    def __init__(self, run_id, worker, epoch, digest, grade, topic, deadline):
        self.run_id = run_id
        self.worker = worker
        self.epoch = epoch
        self.digest = digest
        self.grade = grade
        self.topic = topic
        self.deadline = deadline

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())


async def run_job(run_id: uuid.UUID, worker_id: str, *, force_reclaim: bool = False) -> None:
    """Execute one generation run end to end."""
    deadline = time.monotonic() + settings.pipeline_deadline_seconds  # before ANY waiting

    async with SessionLocal() as session:
        run = await runs.get_run(session, run_id)
        if run is None:
            logger.error("run %s not found", run_id)
            return
        try:
            epoch = await runs.claim_lease(
                session,
                run_id,
                worker_id,
                force_reclaim=force_reclaim,
            )
        except LeaseLost:
            logger.info("run %s already claimed, skipping", run_id)
            return

    ctx = JobContext(
        run_id, worker_id, epoch, run.cache_digest, run.grade, run.topic_original, deadline
    )

    # The guard covers cache lookup, election, follower waiting, and generation.
    guard = asyncio.ensure_future(lease_guard(run_id, worker_id, epoch, asyncio.current_task()))
    try:
        await _dispatch_before_deadline(ctx)
    except asyncio.CancelledError:
        logger.warning("run %s cancelled (lease lost); new owner is responsible", run_id)
        raise
    finally:
        await stop_task(guard)


async def _dispatch_before_deadline(ctx: JobContext) -> None:
    """Bound every dispatch operation, then clean up outside the cancelled scope."""
    try:
        # Per-operation remaining-time checks improve attribution, but cannot
        # independently bound a hung Redis or database call.
        async with asyncio.timeout_at(ctx.deadline):
            await _dispatch(ctx)
    except TimeoutError:
        logger.warning("run %s exceeded the whole-job deadline", ctx.run_id)
        await persist_failure(ctx, "generator_error", "pipeline_deadline_exceeded")


async def _dispatch(ctx: JobContext) -> None:
    """Reuse an existing result if one exists, else generate as elected leader."""
    for _ in range(MAX_ELECTION_ROUNDS):
        if ctx.remaining() <= 0:
            await persist_failure(ctx, "generator_error", "pipeline_deadline_exceeded")
            return

        cached = await get_cached(ctx.digest)
        if cached is not None:
            envelope, status = cached
            await persist_reused(ctx, envelope, status)
            return

        leadership = await single_flight.elect(ctx.digest, ctx.run_id)
        if leadership.is_leader and leadership.token is not None:
            await _lead(ctx, leadership.token)
            return

        # Someone else is generating this. Wait for them, bounded by OUR deadline.
        if await _follow(ctx):
            return
        # Their flight failed or expired — loop and try to win the election.

    logger.warning("run %s: election churned %d times, giving up", ctx.run_id, MAX_ELECTION_ROUNDS)
    await persist_failure(ctx, "generator_error", "single_flight_contention")


async def _follow(ctx: JobContext) -> bool:
    """Wait on the elected leader; True if we reused its result."""
    source_id = await single_flight.follow(ctx.digest, ctx.remaining())
    if source_id is None:
        return False

    result = await single_flight.copy_result(source_id)
    if result is None:
        return False

    status = result.pop("status")
    await persist_reused(ctx, result, status)
    logger.info("run %s reused result from leader %s", ctx.run_id, source_id)
    return True


async def _lead(ctx: JobContext, token: int) -> None:
    """Run the pipeline as elected leader, then publish for any followers."""
    work = asyncio.create_task(
        execute_graph(ctx.run_id, ctx.worker, ctx.epoch, ctx.grade, ctx.topic, ctx.deadline)
    )
    renewer = asyncio.create_task(
        single_flight.renew_leadership(ctx.digest, ctx.run_id, token)
    )
    try:
        done, _ = await asyncio.wait(
            {work, renewer}, timeout=ctx.remaining(), return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            raise PipelineDeadlineExceeded()

        # The renewer only finishes by losing leadership (or by raising an
        # unexpected error). Awaiting it preserves the original exception.
        if renewer in done:
            await renewer

        state = await work
        # Keep renewing through the final transaction. Fencing in persist_result
        # remains the authority if leadership changes during that transaction.
        await persist_result(ctx, token, state)
    except (asyncio.TimeoutError, TimeoutError, PipelineDeadlineExceeded):
        logger.warning("run %s exceeded the pipeline deadline", ctx.run_id)
        await persist_failure(ctx, "generator_error", "pipeline_deadline_exceeded", token)
    except FlightLeadershipLost:
        logger.warning("run %s lost flight leadership; stopping duplicate work", ctx.run_id)
        await stop_task(work)
        # The replacement leader owns the flight. Only terminalize and release
        # our own DB run; never mutate the replacement leader's flight.
        await persist_failure(ctx, "generator_error", "flight_leadership_lost")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("run %s failed unexpectedly", ctx.run_id)
        await persist_failure(ctx, "generator_error", type(exc).__name__, token)
    finally:
        await stop_task(renewer)
        await stop_task(work)


async def stop_task(task: asyncio.Task) -> None:
    """Cancel and consume a background task, including an already-raised result."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task
