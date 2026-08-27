"""Single-flight coordination around a cache digest.

Without this, N kids asking for "Types of angles" at the same moment all miss the
cache and all trigger their own LLM calls — worst exactly when a topic is popular.
One request wins the election and computes; the rest wait and reuse its result.

A follower must not wait on a dead leader, so polling checks the flight's own
lease expiry rather than only its status.
"""

import asyncio
import contextlib
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import settings
from app.core.exceptions import FlightLeadershipLost
from app.db import flights, runs
from app.db.session import SessionLocal
from app.services.envelope import STAGE_FIELDS

logger = logging.getLogger(__name__)

POLL_MIN_SECONDS = 0.5
POLL_MAX_SECONDS = 2.0


@dataclass(frozen=True)
class Leadership:
    is_leader: bool
    token: int | None = None


async def elect(digest: str, run_id: uuid.UUID) -> Leadership:
    """Try to become the leader for this digest."""
    async with SessionLocal() as session:
        token = await flights.try_become_leader(session, digest, run_id)
    return Leadership(is_leader=token is not None, token=token)


async def renew_leadership(digest: str, run_id: uuid.UUID, token: int) -> None:
    """Keep the flight lease alive and signal explicitly if ownership is lost.

    The runner owns cancellation of the graph task. Keeping that decision there
    avoids cancelling SAQ's outer handler and stranding the database run.
    """
    while True:
        await asyncio.sleep(settings.flight_lease_renew_seconds)
        try:
            async with SessionLocal() as session:
                still_leader = await flights.renew_flight(session, digest, run_id, token)
        except Exception:
            logger.exception("flight renewal error for %s", digest[:12])
            continue  # transient DB blip; the lease has slack for a retry

        if not still_leader:
            logger.warning("flight leadership lost for %s", digest[:12])
            raise FlightLeadershipLost(digest)


async def follow(digest: str, budget_seconds: float) -> uuid.UUID | None:
    """Wait for the leader to finish. Returns the run id holding the result.

    Returns None if the leader failed, its lease expired, or our budget ran out —
    the caller then re-runs the election instead of waiting forever.
    """
    waited = 0.0
    while waited < budget_seconds:
        delay = min(random.uniform(POLL_MIN_SECONDS, POLL_MAX_SECONDS), budget_seconds - waited)
        await asyncio.sleep(delay)
        waited += delay

        async with SessionLocal() as session:
            flight = await flights.read_flight(session, digest)

        if flight is None:
            return None
        if flight.status == "done" and flight.result_run_id:
            return flight.result_run_id
        if flight.status == "failed":
            return None  # leader gave up; caller re-elects

        # Still 'in_progress' — but is the leader actually alive?
        if flight.lease_expires_at and flight.lease_expires_at < datetime.now(timezone.utc):
            logger.info("flight %s lease expired; leader looks dead", digest[:12])
            return None

    logger.warning("follower ran out of budget waiting on flight %s", digest[:12])
    return None


async def copy_result(source_run_id: uuid.UUID) -> dict | None:
    """Read the leader's finished envelope so a follower can reuse it verbatim."""
    with contextlib.suppress(Exception):
        async with SessionLocal() as session:
            source = await runs.get_run(session, source_run_id)
        if source is None or source.status not in {"completed_pass", "completed_fail"}:
            return None
        # Built from STAGE_FIELDS rather than listed by hand — the hand-written
        # list silently dropped refinement_count, so a follower showed refined
        # content while reporting zero refinements.
        envelope = {field: getattr(source, field) for field in STAGE_FIELDS}
        return {"status": source.status, **envelope}
    return None
