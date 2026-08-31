"""The Part 2 required API surface.

  POST /generate        runs the full pipeline and returns the RunArtifact
  GET  /history?user_id= returns that user's stored RunArtifacts

Both are unprefixed, exactly as specified, so an evaluator can call them without
knowing anything about the Part 1 UI's `/api` routes.

`POST /generate` is synchronous from the caller's side but does not run the graph
in the request handler. It submits through the same path as the asynchronous
endpoint and waits for the same worker, which is what makes the two surfaces
incapable of drifting: there is one pipeline, and this is a facade over it. The
cost is that the API depends on a running worker — the same dependency the
asynchronous endpoint already had, now visible to the caller as latency.
"""

import asyncio
import logging
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.deps import as_http_error, resolve_user_id, session_id_of
from app.core.config import settings
from app.db import history, runs
from app.db.models import TERMINAL_STATUSES
from app.db.session import SessionLocal, get_session
from app.schemas.api import GenerateRequest, HistoryResponse, UserId
from app.schemas.artifact import RunArtifact
from app.services import submission

logger = logging.getLogger(__name__)
router = APIRouter()

POLL_INTERVAL_SECONDS = 0.5
# The wait ceiling sits above the pipeline deadline and below the reverse proxy's
# read timeout, so a run that overruns is terminated by its own deadline and
# reported here, rather than being cut off mid-flight by the proxy.
WAIT_CEILING_SECONDS = settings.saq_job_timeout_seconds


@router.post("/generate", response_model=RunArtifact)
async def generate(
    body: GenerateRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
) -> RunArtifact:
    """Run the full pipeline for one (grade, topic) and return its audit record."""
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

    artifact = await _await_artifact(result.run_id)
    return RunArtifact.model_validate(artifact)


@router.get("/history", response_model=HistoryResponse)
async def get_history(
    # Annotated form, not `user_id: UserId = Query(...)`: with a bare Query
    # default FastAPI builds the field from the Query alone and the type's
    # StringConstraints are silently dropped, so "bad user" was accepted.
    user_id: Annotated[UserId, Query(description="Owner whose runs to return")],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: AsyncSession = Depends(get_session),
) -> HistoryResponse:
    """Stored RunArtifacts for one user, newest first."""
    stored = await history.list_artifacts(session, user_id, limit=limit, offset=offset)
    legacy = await history.count_legacy(session, user_id)

    artifacts: list[RunArtifact] = []
    for payload in stored:
        try:
            artifacts.append(RunArtifact.model_validate(payload))
        except ValueError:
            # A stored row that no longer parses is a data problem, not a reason
            # to fail the whole listing. Count it with the legacy rows and move on.
            logger.warning("skipping unparsable stored artifact for user %s", user_id)
            legacy += 1

    return HistoryResponse(
        user_id=user_id,
        count=len(artifacts),
        legacy_excluded=legacy,
        artifacts=artifacts,
    )


async def _await_artifact(run_id: uuid.UUID) -> dict:
    """Poll until the run reaches a terminal status, then return its artifact."""
    end = time.monotonic() + WAIT_CEILING_SECONDS

    while time.monotonic() < end:
        async with SessionLocal() as session:
            run = await runs.get_run(session, run_id)

        if run is None:
            raise HTTPException(status_code=404, detail="run disappeared")
        if run.status in TERMINAL_STATUSES:
            if run.run_artifact is None:
                # Every terminal path writes one, so this means the write failed.
                logger.error("run %s is terminal but has no artifact", run_id)
                raise HTTPException(
                    status_code=500, detail="the run finished without an audit artifact"
                )
            return run.run_artifact

        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    raise HTTPException(
        status_code=504,
        detail=f"the pipeline did not finish within {WAIT_CEILING_SECONDS}s",
    )
