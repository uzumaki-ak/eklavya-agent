"""Anthropic Claude provider.

Kept fully working alongside Gemini — switching back is one config value, so a
Claude demo needs only an API key with credits, no code change.

SDK retries are disabled here: Tenacity in client.py is the single retry
authority, and stacking the two would multiply real HTTP attempts.
"""

import logging

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    RateLimitError,
)
from pydantic import BaseModel

from app.agents.providers.base import LLMRoleConfig
from app.core.config import settings

logger = logging.getLogger(__name__)


class ClaudeProvider:
    name = "claude"

    def __init__(self) -> None:
        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key or None,  # None -> SDK env/profile resolution
            max_retries=0,
        )

    async def generate(
        self,
        config: LLMRoleConfig,
        system: str,
        user: str,
        output_format: type[BaseModel],
    ) -> BaseModel:
        response = await self._client.messages.parse(
            model=config.model_id,
            max_tokens=config.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=output_format,
        )
        return response.parsed_output

    def is_retryable(self, exc: BaseException) -> bool:
        if isinstance(exc, (RateLimitError, APITimeoutError, APIConnectionError)):
            return True
        # 408/409 and 5xx are transient. Everything else (401 auth, 400 billing,
        # 403 permission) is permanent — retrying only burns the deadline.
        return isinstance(exc, APIStatusError) and (
            exc.status_code in (408, 409) or exc.status_code >= 500
        )

    def retry_after(self, exc: BaseException) -> float | None:
        response = getattr(exc, "response", None)
        header = response.headers.get("retry-after") if response is not None else None
        try:
            return float(header) if header is not None else None
        except (TypeError, ValueError):
            return None
