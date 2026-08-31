"""Single entry point for every LLM call, provider-agnostic.

Layering matters here (see ARCHITECTURE.md "Concurrency & resilience"):
  - Provider SDK retries are disabled; Tenacity is the only retry authority.
  - The semaphore sits INSIDE the retry loop, so a task doesn't hold a
    concurrency slot while Tenacity sleeps between attempts.
  - Clamping the wait to 0 doesn't stop Tenacity retrying, so there is a
    separate deadline-aware stop condition.
  - A requests-per-minute limiter sits outside the semaphore, because a free
    tier caps the *rate* of calls, which a concurrency limit cannot express.
"""

import asyncio
import time

from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app.agents.providers import (
    GENERATOR_CONFIG,
    REFINER_CONFIG,
    REVIEWER_CONFIG,
    TAGGER_CONFIG,
    LLMRoleConfig,
    get_provider,
)
from app.core.config import settings
from app.core.exceptions import LLMCallTimeout, PipelineDeadlineExceeded
from app.services.rate_limit import RequestsPerMinuteLimiter

__all__ = [
    "call_llm",
    "GENERATOR_CONFIG",
    "REFINER_CONFIG",
    "REVIEWER_CONFIG",
    "TAGGER_CONFIG",
    "LLMRoleConfig",
]

_semaphore = asyncio.Semaphore(settings.llm_max_concurrency)
_rpm = RequestsPerMinuteLimiter(settings.llm_requests_per_minute)


def _clamped_wait(provider, deadline: float):
    """Prefer the provider's own retry hint, else exponential backoff —
    never sleeping past the job deadline."""
    fallback = wait_exponential_jitter(initial=1, max=20)

    def wait(retry_state) -> float:
        exc = retry_state.outcome.exception()
        hinted = provider.retry_after(exc) if exc is not None else None
        base = hinted if hinted is not None else fallback(retry_state)
        return max(0.0, min(base, deadline - time.monotonic()))

    return wait


def _deadline_stop(deadline: float):
    def stop(retry_state) -> bool:
        return time.monotonic() >= deadline

    return stop


async def call_llm(
    config: LLMRoleConfig,
    system: str,
    user: str,
    output_format: type[BaseModel],
    deadline: float,
    counters: dict | None = None,
) -> BaseModel:
    """Make one structured-output call, retrying transient failures within the deadline.

    `counters` (if given) accumulates "transport_attempts" so the pipeline can
    report how much retrying a job actually needed.

    Raises PipelineDeadlineExceeded (terminal) or the last transport error.
    """
    if time.monotonic() >= deadline:
        raise PipelineDeadlineExceeded()

    provider = get_provider()

    @retry(
        stop=stop_after_attempt(settings.transport_max_attempts) | _deadline_stop(deadline),
        wait=_clamped_wait(provider, deadline),
        retry=retry_if_exception(
            lambda e: isinstance(e, LLMCallTimeout) or provider.is_retryable(e)
        ),
        reraise=True,
    )
    async def _attempt() -> BaseModel:
        # Re-checked per attempt so no request starts after the budget is gone.
        # Not in the retry predicate, so Tenacity reraises it immediately.
        if time.monotonic() >= deadline:
            raise PipelineDeadlineExceeded()

        if counters is not None:
            counters["transport_attempts"] = counters.get("transport_attempts", 0) + 1

        await _rpm.acquire(deadline)  # outside the semaphore: a rate cap, not a concurrency cap
        async with _semaphore:
            try:
                async with asyncio.timeout(settings.llm_call_timeout_seconds):
                    return await provider.generate(config, system, user, output_format)
            except TimeoutError as exc:
                # Per-call watchdog only. A pipeline-level timeout cancels from
                # outside this scope and never surfaces here.
                raise LLMCallTimeout() from exc

    return await _attempt()
