"""GET /api/jobs/{id} — poll a run, and an SSE stream for the live stage view."""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import runs
from app.db.models import TERMINAL_STATUSES
from app.db.session import SessionLocal, get_session
from app.schemas.api import JobResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_response(run) -> JobResponse:
    return JobResponse(
        job_id=str(run.id),
        status=run.status,
        grade=run.grade,
        topic=run.topic_original,
        cache_hit=run.cache_hit,
        original_output=run.original_output,
        initial_review=run.initial_review,
        refined_output=run.refined_output,
        final_review=run.final_review,
        tags=run.tags,
        refinement_count=run.refinement_count,
        error_code=run.error_code,
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> JobResponse:
    run = await runs.get_run(session, job_id)
    if run is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _to_response(run)


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: uuid.UUID) -> StreamingResponse:
    """Push stage updates as they land, so the UI can animate the agent flow live."""

    async def events():
        last_payload = None
        for _ in range(300):  # ~5 min ceiling, above the pipeline deadline
            async with SessionLocal() as session:
                run = await runs.get_run(session, job_id)

            if run is None:
                yield f"data: {json.dumps({'error': 'not_found'})}\n\n"
                return

            # by_alias, or the review's verdict ships as "passed" and the UI —
            # which reads the spec's "pass" — renders every approved lesson as a
            # failure. FastAPI applies the alias to `response_model` returns
            # automatically; a hand-rolled dump like this one does not.
            payload = _to_response(run).model_dump(mode="json", by_alias=True)
            if payload != last_payload:  # only push real changes
                yield f"data: {json.dumps(payload)}\n\n"
                last_payload = payload

            if run.status in TERMINAL_STATUSES:
                return

            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
