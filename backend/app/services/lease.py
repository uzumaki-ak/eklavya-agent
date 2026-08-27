"""Background lease guard.

One task per running job renews the DB lease on a timer, covering everything the
job does — cache lookup, single-flight waiting, LLM calls, backoff sleeps. If a
renewal comes back empty, another worker has taken over and this one is cancelled
immediately rather than being allowed to finish and write a stale result.
"""

import asyncio
import logging
import uuid

from app.core.config import settings
from app.core.exceptions import LeaseLost
from app.db.runs import renew_lease
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


async def lease_guard(
    run_id: uuid.UUID, worker: str, epoch: int, target: asyncio.Task
) -> None:
    """Renew until cancelled; cancel `target` if the lease is lost."""
    while True:
        await asyncio.sleep(settings.job_lease_renew_seconds)
        try:
            async with SessionLocal() as session:
                await renew_lease(session, run_id, worker, epoch)
        except LeaseLost:
            logger.warning("lease lost for run %s, cancelling work", run_id)
            target.cancel()
            return
        except Exception:
            # A transient DB blip shouldn't kill a healthy job; the lease has
            # enough slack for the next attempt to succeed.
            logger.exception("lease renewal error for run %s", run_id)
