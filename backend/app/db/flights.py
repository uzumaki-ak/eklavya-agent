"""content_flights repository — single-flight election.

Prevents N concurrent requests for the same brand-new topic from all calling the
LLM. One wins the election and computes; the rest poll and reuse its result.

Note: a 'done' flight is NEVER taken over. A request arriving just after the
leader finished must reuse result_run_id, not recompute from scratch.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import ContentFlight


def _expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=settings.flight_lease_seconds)


async def try_become_leader(
    session: AsyncSession, digest: str, run_id: uuid.UUID
) -> int | None:
    """Returns our fencing token if we won, else None (we're a follower).

    Takeover is allowed only for a failed flight or an expired in-progress one.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        insert(ContentFlight)
        .values(
            cache_digest=digest,
            leader_run_id=run_id,
            lease_expires_at=_expiry(),
            fencing_token=1,
            status="in_progress",
        )
        .on_conflict_do_update(
            index_elements=["cache_digest"],
            set_={
                "leader_run_id": run_id,
                "lease_expires_at": _expiry(),
                "fencing_token": ContentFlight.fencing_token + 1,
                "status": "in_progress",
            },
            where=(
                (ContentFlight.status == "failed")
                | ((ContentFlight.status == "in_progress") & (ContentFlight.lease_expires_at < now))
            ),
        )
        .returning(ContentFlight.fencing_token)
    )
    token = (await session.execute(stmt)).scalar_one_or_none()
    await session.commit()
    return token


async def read_flight(session: AsyncSession, digest: str) -> ContentFlight | None:
    """Follower path — the election returns zero rows, so read the row directly."""
    return (
        await session.execute(select(ContentFlight).where(ContentFlight.cache_digest == digest))
    ).scalar_one_or_none()


async def renew_flight(session: AsyncSession, digest: str, run_id: uuid.UUID, token: int) -> bool:
    """Returns False if leadership was lost — the caller MUST act on that."""
    stmt = (
        update(ContentFlight)
        .where(
            ContentFlight.cache_digest == digest,
            ContentFlight.leader_run_id == run_id,
            ContentFlight.fencing_token == token,
        )
        .values(lease_expires_at=_expiry())
        .returning(ContentFlight.fencing_token)
    )
    result = (await session.execute(stmt)).scalar_one_or_none()
    await session.commit()
    return result is not None


async def complete_flight(
    session: AsyncSession, digest: str, run_id: uuid.UUID, token: int, *, success: bool
) -> bool:
    """Publish the outcome, fenced.

    The caller commits the run's own completion in the SAME transaction, so
    'done' can never become visible before the referenced result is durable.
    """
    stmt = (
        update(ContentFlight)
        .where(
            ContentFlight.cache_digest == digest,
            ContentFlight.leader_run_id == run_id,
            ContentFlight.fencing_token == token,
        )
        .values(
            status="done" if success else "failed",
            result_run_id=run_id if success else None,
        )
        .returning(ContentFlight.fencing_token)
    )
    result = (await session.execute(stmt)).scalar_one_or_none()
    return result is not None
