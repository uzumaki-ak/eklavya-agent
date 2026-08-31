"""Shared submission path for both API surfaces.

Part 2 requires a synchronous `POST /generate` that returns a RunArtifact; Part 1
built an asynchronous `POST /api/generate` that returns a job id for the UI to
stream. Both are kept, and both come through here.

They do not merely share code — they share the *execution*. Neither runs the
graph itself: both create a run, consult the cache, and enqueue, and the
synchronous endpoint then waits for the same worker to finish the same job. There
is one pipeline, so there is nothing for a second implementation to drift from.
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import runs
from app.db.models import GenerationRun
from app.pipeline.artifact import artifact_json, build_artifact, meta_for_run
from app.services.cache import cache_digest, get_cached
from app.services.canonicalize import canonicalize_topic
from app.services.envelope import summary_from_envelope
from app.services.queue import try_enqueue_run

logger = logging.getLogger(__name__)


class EmptyTopic(ValueError):
    """The topic canonicalized to nothing."""


class IdempotencyConflict(ValueError):
    """The key was reused with a different payload."""


class QueueUnavailable(RuntimeError):
    """The job could not be placed on the queue."""


@dataclass(frozen=True)
class Submission:
    run_id: uuid.UUID
    status: str
    cache_hit: bool


def _request_hash(user_id: str, grade: int, topic_canonical: str) -> str:
    """Binds an idempotency key to its payload, so reuse with different input is caught."""
    return hashlib.sha256(
        json.dumps(
            {"user_id": user_id, "grade": grade, "topic": topic_canonical},
            sort_keys=True,
        ).encode()
    ).hexdigest()


async def submit(
    session: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    grade: int,
    topic: str,
    idempotency_key: str | None = None,
) -> Submission:
    """Create or find the run, serve it from cache if possible, else enqueue it."""
    canonical = canonicalize_topic(topic)
    if not canonical:
        raise EmptyTopic("topic must contain at least one word")

    digest = cache_digest(grade, canonical)
    try:
        run, created = await runs.get_or_create_run(
            session,
            session_id=session_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
            request_hash=_request_hash(user_id, grade, canonical),
            grade=grade,
            topic_original=topic,
            topic_canonical=canonical,
            cache_digest=digest,
        )
    except ValueError as exc:
        # Reusing a key with a different payload is a client error, not a silent
        # hand-back of unrelated content.
        raise IdempotencyConflict(str(exc)) from exc

    if not created:
        # Same key, same payload. If the original never made it onto the queue
        # (e.g. Redis was down), re-enqueue rather than returning a row that
        # will sit at "queued" forever. SAQ's job key dedupes a live job.
        if run.status == "queued" and run.lease_owner is None:
            if not await try_enqueue_run(run.id):
                raise QueueUnavailable("could not restart the queued job")
        return Submission(run.id, run.status, run.cache_hit)

    cached = await get_cached(digest)
    if cached is not None:
        envelope, status = cached  # status comes from the cache, never assumed
        await _apply_cached(session, run, envelope, status, user_id)
        return Submission(run.id, status, True)

    if not await try_enqueue_run(run.id):
        raise QueueUnavailable("could not start the job right now")
    return Submission(run.id, "queued", False)


async def _apply_cached(
    session: AsyncSession,
    run: GenerationRun,
    envelope: dict,
    status: str,
    user_id: str,
) -> None:
    """Copy a cached envelope onto this run and build *this run's* artifact.

    The content is reused; the audit record is not. It is rebuilt with this run's
    own id, owner and timestamps and `cache_hit=True`, through the same builder
    the worker uses — so a cache hit is honestly recorded rather than presented
    as work this run performed.
    """
    now = datetime.now(timezone.utc)
    artifact = build_artifact(
        envelope,
        meta_for_run(
            run_id=str(run.id),
            user_id=user_id,
            grade=run.grade,
            topic=run.topic_original,
            started_at=run.created_at or now,
            pipeline_status=status,
            cache_hit=True,
        ),
    )
    await session.execute(
        update(GenerationRun)
        .where(GenerationRun.id == run.id)
        .values(
            status=status,
            cache_hit=True,
            current_stage="done",
            completed_at=now,
            tags=envelope.get("tags"),
            refinement_count=envelope.get("refinement_count", 0) or 0,
            run_artifact=artifact_json(artifact),
            **summary_from_envelope(envelope),
        )
    )
    await session.commit()
