"""Requests-per-minute limiter.

A semaphore caps how many calls run *at once*; it says nothing about how many
run *per minute*. This optional limiter adds a configurable local safety cap.

It uses a conservative sliding 60-second window. Provider limits vary and are
enforced per Google project, while this object coordinates only one process.
"""

import asyncio
import time
from collections import deque

from app.core.exceptions import PipelineDeadlineExceeded

WINDOW_SECONDS = 60.0


class RequestsPerMinuteLimiter:
    def __init__(self, max_per_minute: int) -> None:
        self._max = max_per_minute
        self._times: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, deadline: float) -> None:
        """Block until a slot is free. Raises if waiting would pass the deadline.

        Disabled entirely when max_per_minute <= 0, so a paid tier pays nothing
        for this.
        """
        if self._max <= 0:
            return

        # Keep the lock while the oldest waiter sleeps. asyncio.Lock is FIFO, so
        # a stream of new calls cannot repeatedly steal the next available slot.
        async with self._lock:
            while True:
                now = time.monotonic()
                self._evict_expired(now)

                if len(self._times) < self._max:
                    self._times.append(now)
                    return

                # Oldest call in the window decides when the next slot opens.
                wait_for = max(0.0, (self._times[0] + WINDOW_SECONDS) - now)
                if now + wait_for >= deadline:
                    # Sleeping would outlast the job; fail now rather than at wake-up.
                    raise PipelineDeadlineExceeded()

                await asyncio.sleep(wait_for)

    def _evict_expired(self, now: float) -> None:
        cutoff = now - WINDOW_SECONDS
        while self._times and self._times[0] <= cutoff:
            self._times.popleft()
