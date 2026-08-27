"""Google Gemini provider.

Uses the google-genai SDK's native structured output: the Pydantic model's JSON
Schema goes in as `response_json_schema`, and `response.parsed` is validated.

Gemini quotas vary by model, project, and tier. The process-local limiter is a
configurable safety cap; provider 429s remain the source of truth.
"""

import logging
import re
from collections.abc import Mapping, Sequence

import httpx
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from pydantic import BaseModel

from app.agents.providers.base import LLMRoleConfig
from app.core.config import settings
from app.core.exceptions import LLMStructuredOutputError

logger = logging.getLogger(__name__)

# Transient HTTP codes. 429 = rate limited, 5xx = server-side.
_RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}

# Gemini reports its retry delay inside the error body, e.g. "retryDelay": "27s"
_RETRY_DELAY_RE = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"')


class GeminiProvider:
    name = "gemini"

    def __init__(self) -> None:
        # The SDK otherwise performs up to five retries internally. Keep one
        # retry authority (client.py/Tenacity), so per-call and pipeline
        # deadlines remain real rather than multiplying invisibly.
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                timeout=int(settings.llm_call_timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    async def generate(
        self,
        config: LLMRoleConfig,
        system: str,
        user: str,
        output_format: type[BaseModel],
    ) -> BaseModel:
        response = await self._client.aio.models.generate_content(
            model=config.model_id,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=config.max_tokens,
                response_mime_type="application/json",
                response_json_schema=output_format.model_json_schema(),
                thinking_config=types.ThinkingConfig(
                    thinking_level=settings.gemini_thinking_level
                ),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )

        parsed = response.parsed
        if parsed is None:
            # Schema-constrained decoding can still fail (safety stop, truncation).
            raise LLMStructuredOutputError(
                f"Gemini returned no parsable {output_format.__name__}; "
                f"finish_reason={_finish_reason(response)}"
            )
        return parsed if isinstance(parsed, output_format) else output_format.model_validate(parsed)

    def is_retryable(self, exc: BaseException) -> bool:
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
            return True
        if isinstance(exc, genai_errors.APIError):
            # A per-day quota cannot recover during this request. Retrying it
            # only makes the child wait before receiving the same answer.
            if getattr(exc, "code", None) == 429 and "GenerateRequestsPerDay" in str(exc):
                return False
            return getattr(exc, "code", None) in _RETRYABLE_CODES
        return False

    def retry_after(self, exc: BaseException) -> float | None:
        """Honour a structured Google ``retryDelay`` hint when present."""
        hinted = _retry_delay_from_details(getattr(exc, "details", None))
        if hinted is not None:
            return hinted

        # Older SDK/error shapes expose the body only through ``str(exc)``.
        match = _RETRY_DELAY_RE.search(str(exc))
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None


def _retry_delay_from_details(value: object) -> float | None:
    """Find a protobuf-style retryDelay recursively in an API error body."""
    if isinstance(value, Mapping):
        delay = value.get("retryDelay")
        if isinstance(delay, str):
            match = re.fullmatch(r"(\d+(?:\.\d+)?)s", delay)
            if match:
                return float(match.group(1))
        for nested in value.values():
            found = _retry_delay_from_details(nested)
            if found is not None:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            found = _retry_delay_from_details(nested)
            if found is not None:
                return found
    return None


def _finish_reason(response) -> str:
    try:
        return str(response.candidates[0].finish_reason)
    except (AttributeError, IndexError, TypeError):
        return "unknown"
