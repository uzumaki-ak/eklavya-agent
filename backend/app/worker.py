"""SAQ worker entry point: `python -m app.worker`."""

import asyncio
import contextlib
import logging
import os
import socket
import uuid

from app.core.config import settings
from app.pipeline.runner import run_job
from app.services.queue import queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Stable per-process identity — this is what the DB lease is held under.
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"

# Must be comfortably below the job's heartbeat, or SAQ marks a healthy
# long-running job as stuck and sweeps it.
HEARTBEAT_INTERVAL_SECONDS = 10


async def _beat(job) -> None:
    """Refresh SAQ's heartbeat for as long as the job runs.

    SAQ requires explicit `job.update()` calls; a single call at start is not
    enough for a pipeline that legitimately runs for minutes.
    """
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        try:
            await job.update()
        except Exception:
            logger.exception("heartbeat update failed")


async def run_pipeline(ctx, *, run_id: str) -> None:
    """Job handler."""
    job = ctx.get("job")
    beat = asyncio.ensure_future(_beat(job)) if job is not None else None
    # A retry means SAQ declared the previous attempt dead. Reclaim its DB
    # lease immediately instead of finishing the retry and orphaning the UI.
    force_reclaim = job is not None and getattr(job, "attempts", 1) > 1

    try:
        await run_job(uuid.UUID(run_id), WORKER_ID, force_reclaim=force_reclaim)
    finally:
        if beat is not None:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat


async def startup(ctx) -> None:
    logger.info("worker %s ready (concurrency=%d)", WORKER_ID, settings.llm_max_concurrency)


async def shutdown(ctx) -> None:
    from app.db.session import engine

    await engine.dispose()


settings_dict = {
    "queue": queue,
    "functions": [run_pipeline],
    "concurrency": settings.llm_max_concurrency,
    "startup": startup,
    "shutdown": shutdown,
}

if __name__ == "__main__":
    from saq.worker import start

    start("app.worker.settings_dict")
