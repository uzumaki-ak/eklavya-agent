"""Provider interface.

Both agents call through this, so swapping Claude for Gemini changes one config
value rather than any agent code. Each provider owns three things the retry
layer needs: how to make the call, which of its errors are transient, and how
long its rate-limit responses ask us to wait.
"""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class LLMRoleConfig:
    """One immutable config per role, used at both call time and cache-key time
    so the two can never drift apart."""

    role: str
    model_id: str
    max_tokens: int


class LLMProvider(Protocol):
    """What the pipeline needs from any model vendor."""

    name: str

    async def generate(
        self,
        config: LLMRoleConfig,
        system: str,
        user: str,
        output_format: type[BaseModel],
    ) -> BaseModel:
        """Return a validated instance of `output_format`, or raise."""
        ...

    def is_retryable(self, exc: BaseException) -> bool:
        """True for transient failures (rate limits, timeouts, 5xx).

        Must be False for auth/billing/bad-request errors — retrying those
        wastes the budget and never succeeds.
        """
        ...

    def retry_after(self, exc: BaseException) -> float | None:
        """Server-requested wait in seconds, if the error carries one."""
        ...
