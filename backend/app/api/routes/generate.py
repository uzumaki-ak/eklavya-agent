"""POST /api/generate — enqueue a pipeline run and return a job id.

Part 1's asynchronous surface, kept for the streaming UI. The required
synchronous `POST /generate` lives in `pipeline.py`; both call
`app.services.submission.submit`, and both are executed by the same worker.
"""

import logging

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.deps import as_http_error, resolve_user_id, session_id_of
from app.db.session import get_session
from app.schemas.api import GenerateRequest, GenerateResponse
from app.services import submission

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/generate", response_model=GenerateResponse, status_code=202)
async def generate(
    body: GenerateRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
) -> GenerateResponse:
    try:
        result = await submission.submit(
            session,
            session_id=session_id_of(request),
            user_id=resolve_user_id(request, body.user_id),
            grade=body.grade,
            topic=body.topic,
            idempotency_key=idempotency_key,
        )
    except (submission.EmptyTopic, submission.IdempotencyConflict,
            submission.QueueUnavailable) as exc:
        raise as_http_error(exc) from exc

    return GenerateResponse(
        job_id=str(result.run_id), status=result.status, cache_hit=result.cache_hit
    )
