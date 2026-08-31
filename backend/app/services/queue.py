"""SAQ queue setup.

SAQ's defaults would break this workload: a 10s job timeout and no heartbeat,
against a pipeline whose budget is 240s. Both are set explicitly below.
"""

import logging
import uuid

from saq import Queue

from app.core.config import settings

logger = logging.getLogger(__name__)

queue = Queue.from_url(settings.redis_url)

# SAQ compares `retries > attempts`, so retries=1 yields NO retry at all.
# 2 means "one retry after the first attempt".
JOB_RETRIES = 2

# The worker refreshes this every 10s while a job runs (see app/worker.py).
JOB_HEARTBEAT_SECONDS = 30


async def enqueue_run(run_id: uuid.UUID) -> None:
    """Queue one pipeline run.

    `key` dedupes the enqueue itself; it is NOT the correctness boundary —
    duplicate *execution* is prevented by DB leasing in app/db/runs.py.
    """
    await queue.enqueue(
        "run_pipeline",
        key=f"run:{run_id}",
        run_id=str(run_id),
        timeout=settings.saq_job_timeout_seconds,  # safety net above the pipeline deadline
        heartbeat=JOB_HEARTBEAT_SECONDS,
        retries=JOB_RETRIES,
    )


async def try_enqueue_run(run_id: uuid.UUID) -> bool:
    """Enqueue without raising. False means the row is durable but unqueued —
    the caller should surface that rather than pretend the job is running."""
    try:
        await enqueue_run(run_id)
        return True
    except Exception:
        logger.exception("enqueue failed for run %s", run_id)
        return False
