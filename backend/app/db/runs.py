"""generation_runs repository — creation, leasing, and fenced writes.

Transaction policy: these functions FLUSH, they never COMMIT. The caller owns the
transaction boundary, so a run's terminal state and its flight publication can be
committed together atomically.

Every write is fenced on (id, lease_owner, lease_epoch). A worker that lost its
lease affects zero rows and must discard its result rather than commit it.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.providers import GENERATOR_CONFIG, REVIEWER_CONFIG
from app.agents.prompts import PROMPT_VERSIONS
from app.core.config import settings
from app.core.exceptions import LeaseLost
from app.db.models import GenerationRun


async def get_or_create_run(
    session: AsyncSession,
    *,
    session_id: str,
    idempotency_key: str | None,
    request_hash: str,
    grade: int,
    topic_original: str,
    topic_canonical: str,
    cache_digest: str,
) -> tuple[GenerationRun, bool]:
    """Returns (run, created). Raises ValueError if a key is reused with a different payload."""
    stmt = (
        insert(GenerationRun)
        .values(
            id=uuid.uuid4(),
            session_id=session_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            grade=grade,
            topic_original=topic_original,
            topic_canonical=topic_canonical,
            canonicalizer_version=settings.canonicalizer_version,
            cache_digest=cache_digest,
            # Provenance: which models/prompts produced this row's content.
            # Recorded at creation so a later prompt change can't rewrite history.
            generator_model=GENERATOR_CONFIG.model_id,
            reviewer_model=REVIEWER_CONFIG.model_id,
            generator_prompt_version=PROMPT_VERSIONS["generator"],
            reviewer_prompt_version=PROMPT_VERSIONS["reviewer"],
            schema_version=settings.schema_version,
            status="queued",
        )
        .on_conflict_do_nothing(index_elements=["session_id", "idempotency_key"])
        .returning(GenerationRun)
    )
    created = (await session.execute(stmt)).scalar_one_or_none()
    if created is not None:
        await session.commit()
        return created, True

    # Conflict: an existing run owns this key. Reusing it with a different
    # payload is a client error, not a silent hand-back of unrelated content.
    existing = (
        await session.execute(
            select(GenerationRun).where(
                and_(
                    GenerationRun.session_id == session_id,
                    GenerationRun.idempotency_key == idempotency_key,
                )
            )
        )
    ).scalar_one()

    if existing.request_hash != request_hash:
        raise ValueError("idempotency key reused with a different payload")
    return existing, False


async def claim_lease(
    session: AsyncSession,
    run_id: uuid.UUID,
    worker: str,
    *,
    force_reclaim: bool = False,
) -> int:
    """Take ownership and bump the fencing epoch.

    A queue retry can reclaim an unexpired lease because SAQ has already
    declared the previous attempt dead, such as after a worker restart.
    """
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.job_lease_seconds)
    lease_available = (
        True
        if force_reclaim
        else (GenerationRun.lease_owner.is_(None))
        | (GenerationRun.lease_expires_at < datetime.now(timezone.utc))
    )
    stmt = (
        update(GenerationRun)
        .where(
            GenerationRun.id == run_id,
            lease_available,
        )
        .values(
            lease_owner=worker,
            lease_expires_at=expires,
            lease_epoch=GenerationRun.lease_epoch + 1,
            status="processing",
            started_at=func.now(),
        )
        .returning(GenerationRun.lease_epoch)
    )
    epoch = (await session.execute(stmt)).scalar_one_or_none()
    await session.commit()
    if epoch is None:
        raise LeaseLost(f"run {run_id} is held by another worker")
    return epoch


async def renew_lease(session: AsyncSession, run_id: uuid.UUID, worker: str, epoch: int) -> None:
    """Extend the lease without touching the epoch. Zero rows means we were reclaimed."""
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.job_lease_seconds)
    stmt = (
        update(GenerationRun)
        .where(
            GenerationRun.id == run_id,
            GenerationRun.lease_owner == worker,
            GenerationRun.lease_epoch == epoch,
        )
        .values(lease_expires_at=expires)
        .returning(GenerationRun.lease_epoch)
    )
    result = (await session.execute(stmt)).scalar_one_or_none()
    await session.commit()
    if result is None:
        raise LeaseLost(f"lease for run {run_id} was reclaimed")


async def write_stage(
    session: AsyncSession, run_id: uuid.UUID, worker: str, epoch: int, **fields
) -> None:
    """Fenced stage write. Never bumps the epoch. Flushes only — caller commits."""
    stmt = (
        update(GenerationRun)
        .where(
            GenerationRun.id == run_id,
            GenerationRun.lease_owner == worker,
            GenerationRun.lease_epoch == epoch,
        )
        .values(**fields)
        .returning(GenerationRun.lease_epoch)
    )
    result = (await session.execute(stmt)).scalar_one_or_none()
    if result is None:
        raise LeaseLost(f"cannot write to run {run_id}: lease reclaimed")


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> GenerationRun | None:
    return (
        await session.execute(select(GenerationRun).where(GenerationRun.id == run_id))
    ).scalar_one_or_none()
