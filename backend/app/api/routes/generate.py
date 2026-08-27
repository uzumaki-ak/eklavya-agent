"""POST /api/generate — enqueue a pipeline run."""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import runs
from app.db.models import GenerationRun
from app.db.session import get_session
from app.schemas.api import GenerateRequest, GenerateResponse
from app.services.cache import cache_digest, get_cached
from app.services.canonicalize import canonicalize_topic
from app.services.queue import try_enqueue_run

logger = logging.getLogger(__name__)
router = APIRouter()


def _request_hash(grade: int, topic_canonical: str) -> str:
    """Binds an idempotency key to its payload, so reuse with different input is caught."""
    return hashlib.sha256(
        json.dumps({"grade": grade, "topic": topic_canonical}, sort_keys=True).encode()
    ).hexdigest()


def _session_id(request: Request) -> str:
    """Anonymous session — no auth required by the spec."""
    return request.headers.get("x-session-id") or (request.client.host if request.client else "anon")


@router.post("/generate", response_model=GenerateResponse, status_code=202)
async def generate(
    body: GenerateRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
) -> GenerateResponse:
    canonical = canonicalize_topic(body.topic)
    if not canonical:
        raise HTTPException(status_code=422, detail="topic must contain at least one word")

    digest = cache_digest(body.grade, canonical)

    try:
        run, created = await runs.get_or_create_run(
            session,
            session_id=_session_id(request),
            idempotency_key=idempotency_key,
            request_hash=_request_hash(body.grade, canonical),
            grade=body.grade,
            topic_original=body.topic,
            topic_canonical=canonical,
            cache_digest=digest,
        )
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail="This Idempotency-Key was already used with a different grade/topic.",
        )

    if not created:
        # Same key, same payload. If the original never made it onto the queue
        # (e.g. Redis was down), re-enqueue rather than returning a row that
        # will sit at "queued" forever. SAQ's job key dedupes a live job.
        if run.status == "queued" and run.lease_owner is None:
            if not await try_enqueue_run(run.id):
                raise HTTPException(
                    status_code=503,
                    detail="Could not restart the queued job. Please try again in a moment.",
                )
        return GenerateResponse(job_id=str(run.id), status=run.status, cache_hit=run.cache_hit)

    # Serve straight from cache when this exact content already exists.
    cached = await get_cached(digest)
    if cached is not None:
        envelope, status = cached  # status comes from the cache, never assumed
        await _apply_cached(session, run.id, envelope, status)
        return GenerateResponse(job_id=str(run.id), status=status, cache_hit=True)

    if not await try_enqueue_run(run.id):
        raise HTTPException(
            status_code=503,
            detail="Could not start the job right now. Please try again in a moment.",
        )
    return GenerateResponse(job_id=str(run.id), status="queued")


async def _apply_cached(
    session: AsyncSession, run_id: uuid.UUID, envelope: dict, status: str
) -> None:
    """Copy a cached envelope onto this run. All stages preserved for the UI."""
    await session.execute(
        update(GenerationRun)
        .where(GenerationRun.id == run_id)
        .values(
            status=status,
            cache_hit=True,
            current_stage="done",
            completed_at=datetime.now(timezone.utc),
            **envelope,
        )
    )
    await session.commit()
