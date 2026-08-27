import asyncio
import time

import pytest

from app.core.exceptions import PipelineDeadlineExceeded
from app.services import rate_limit as rate_limit_module
from app.services.rate_limit import RequestsPerMinuteLimiter


@pytest.mark.asyncio
async def test_limiter_is_fifo_under_contention(monkeypatch):
    monkeypatch.setattr(rate_limit_module, "WINDOW_SECONDS", 0.02)
    limiter = RequestsPerMinuteLimiter(1)
    deadline = time.monotonic() + 1
    order = []

    async def acquire(number):
        await limiter.acquire(deadline)
        order.append(number)

    await asyncio.gather(*(acquire(number) for number in range(4)))
    assert order == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_limiter_rejects_wait_beyond_deadline(monkeypatch):
    monkeypatch.setattr(rate_limit_module, "WINDOW_SECONDS", 1.0)
    limiter = RequestsPerMinuteLimiter(1)
    await limiter.acquire(time.monotonic() + 1)

    with pytest.raises(PipelineDeadlineExceeded):
        await limiter.acquire(time.monotonic() + 0.01)


@pytest.mark.asyncio
async def test_non_positive_limit_is_disabled():
    await RequestsPerMinuteLimiter(0).acquire(time.monotonic() - 1)
