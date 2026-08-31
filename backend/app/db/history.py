"""Reads backing GET /history.

Kept apart from `runs.py`, which owns the write path and its leasing rules —
history is a plain, unfenced read and shares none of that machinery.

Legacy safety: rows written before Part 2 have no `run_artifact`; terminal rows
in that state are counted. Stored artifacts are not filtered by the application's
current schema version: a version bump must not erase a valid audit history. The
API validates each payload and counts any genuinely incompatible artifact rather
than failing the whole response.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TERMINAL_STATUSES, GenerationRun


async def list_artifacts(
    session: AsyncSession, user_id: str, *, limit: int = 20, offset: int = 0
) -> list[dict]:
    """Stored RunArtifacts for one user, newest first."""
    stmt = (
        select(GenerationRun.run_artifact)
        .where(
            GenerationRun.user_id == user_id,
            GenerationRun.run_artifact.isnot(None),
        )
        .order_by(GenerationRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [row for row in (await session.execute(stmt)).scalars() if row]


async def count_legacy(session: AsyncSession, user_id: str) -> int:
    """Terminal runs that cannot supply an artifact, including null-version rows."""
    stmt = select(func.count()).select_from(GenerationRun).where(
        GenerationRun.user_id == user_id,
        GenerationRun.status.in_(TERMINAL_STATUSES),
        GenerationRun.run_artifact.is_(None),
    )
    return (await session.execute(stmt)).scalar_one()


async def get_artifact(session: AsyncSession, run_id: uuid.UUID) -> dict | None:
    """One run's stored artifact, or None if it has not finished or is legacy."""
    stmt = select(GenerationRun.run_artifact).where(GenerationRun.id == run_id)
    return (await session.execute(stmt)).scalar_one_or_none()
