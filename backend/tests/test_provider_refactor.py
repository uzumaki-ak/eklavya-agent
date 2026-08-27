import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from google.genai import errors as genai_errors

from app.agents import generator as generator_module
from app.agents.providers import gemini as gemini_module
from app.agents.generator import ExecutionContext, GeneratorAgent
from app.agents.providers.base import LLMRoleConfig
from app.agents.providers.gemini import GeminiProvider, _retry_delay_from_details
from app.core.config import Settings, settings
from app.core.exceptions import LLMStructuredOutputError
from app.schemas.content import GeneratorInput, GeneratorOutput
from app.services.cache import cache_digest


@pytest.mark.asyncio
async def test_current_gemini_bindings_accept_pydantic_schema():
    provider = GeminiProvider.__new__(GeminiProvider)
    parsed = GeneratorOutput(
        explanation="A right angle is a square corner.",
        mcqs=[
            {
                "question": "Which is a right angle?",
                "options": ["90 degrees", "20 degrees", "40 degrees", "180 degrees"],
                "answer": "90 degrees",
            }
        ],
    )
    generate = AsyncMock(return_value=SimpleNamespace(parsed=parsed))
    provider._client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    )

    result = await provider.generate(
        LLMRoleConfig("generator", "gemini-3.7-flash", 4096),
        "system",
        "user",
        GeneratorOutput,
    )

    assert result == parsed
    config = generate.await_args.kwargs["config"]
    assert config.system_instruction == "system"
    assert config.max_output_tokens == 4096
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == GeneratorOutput.model_json_schema()
    assert config.thinking_config.thinking_level.value == "LOW"
    assert config.automatic_function_calling.disable is True


def test_gemini_sdk_retries_are_disabled(monkeypatch):
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(gemini_module.genai, "Client", fake_client)

    GeminiProvider()

    http_options = captured["http_options"]
    assert http_options.retry_options.attempts == 1
    assert http_options.timeout == int(settings.llm_call_timeout_seconds * 1000)


@pytest.mark.asyncio
async def test_gemini_none_parsed_uses_repairable_exception():
    provider = GeminiProvider.__new__(GeminiProvider)
    response = SimpleNamespace(parsed=None, candidates=[])
    provider._client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(return_value=response)))
    )

    with pytest.raises(LLMStructuredOutputError):
        await provider.generate(
            LLMRoleConfig("generator", "gemini-3.7-flash", 4096),
            "system",
            "user",
            GeneratorOutput,
        )


@pytest.mark.asyncio
async def test_generator_repairs_provider_parse_failure(monkeypatch):
    valid = GeneratorOutput(
        explanation="An angle is made when two rays meet.",
        mcqs=[
            {
                "question": "What makes an angle?",
                "options": ["Two rays", "One dot", "Three circles", "No lines"],
                "answer": "Two rays",
            }
        ],
    )
    call = AsyncMock(side_effect=[LLMStructuredOutputError("bad output"), valid])
    monkeypatch.setattr(generator_module, "call_llm", call)

    ctx = ExecutionContext(deadline=time.monotonic() + 10)
    result = await GeneratorAgent().run(GeneratorInput(grade=4, topic="Angles"), ctx)

    assert result == valid
    assert ctx.schema_repair_attempts == 1
    assert "previous response was rejected" in call.await_args_list[1].kwargs["user"]


def test_gemini_retry_classification_and_structured_delay():
    provider = GeminiProvider.__new__(GeminiProvider)
    rate_error = genai_errors.APIError(
        429,
        {"error": {"details": [{"retryDelay": "2.5s"}]}},
    )

    assert provider.is_retryable(rate_error)
    assert provider.is_retryable(httpx.ConnectError("network unavailable"))
    assert not provider.is_retryable(genai_errors.APIError(400, {"error": {}}))
    assert provider.retry_after(rate_error) == 2.5
    assert _retry_delay_from_details({"nested": [{"retryDelay": "3s"}]}) == 3.0


def test_gemini_does_not_retry_daily_quota_exhaustion():
    provider = GeminiProvider.__new__(GeminiProvider)
    daily_quota = genai_errors.APIError(
        429,
        {"error": {"message": "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"}},
    )

    assert not provider.is_retryable(daily_quota)


def test_cache_identity_includes_provider():
    original = settings.llm_provider
    try:
        settings.llm_provider = "gemini"
        gemini_digest = cache_digest(4, "types of angles")
        settings.llm_provider = "claude"
        claude_digest = cache_digest(4, "types of angles")
    finally:
        settings.llm_provider = original

    assert gemini_digest != claude_digest


def test_provider_and_model_ids_must_match():
    with pytest.raises(ValueError, match="does not match"):
        Settings(
            llm_provider="claude",
            generator_model_id="gemini-3.7-flash",
            reviewer_model_id="gemini-3.7-flash",
        )
