import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from google.genai import errors as genai_errors

from app.agents import execution as execution_module
from app.agents.providers import gemini as gemini_module
from app.agents.execution import ExecutionContext
from app.agents.generator import GeneratorAgent
from app.agents.providers.base import LLMRoleConfig
from app.agents.providers.gemini import GeminiProvider, _retry_delay_from_details
from app.core.config import Settings, settings
from app.core.exceptions import LLMStructuredOutputError
from app.schemas.content import GeneratorInput, GeneratorOutput
from app.services import cache as cache_module
from app.services.cache import cache_digest
from tests.factories import draft


@pytest.mark.asyncio
async def test_current_gemini_bindings_accept_pydantic_schema():
    provider = GeminiProvider.__new__(GeminiProvider)
    parsed = GeneratorOutput.model_validate(draft(grade=4))
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
    # Derived from settings, not hard-coded: the shipped level is a measured
    # choice that may change, and this test is about the binding, not the value.
    assert config.thinking_config.thinking_level.value == (
        settings.gemini_thinking_level.upper()
    )
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
    valid = GeneratorOutput.model_validate(draft(grade=4))
    call = AsyncMock(side_effect=[LLMStructuredOutputError("bad output"), valid])
    monkeypatch.setattr(execution_module, "call_llm", call)

    ctx = ExecutionContext(deadline=time.monotonic() + 10)
    result = await GeneratorAgent().run(GeneratorInput(grade=4, topic="Angles"), ctx)

    assert result.explanation == valid.explanation
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


def test_cache_identity_includes_the_thinking_level():
    """Reasoning effort changes the output, so it must change the cache key."""
    original = settings.gemini_thinking_level
    try:
        settings.gemini_thinking_level = "low"
        low = cache_digest(4, "types of angles")
        settings.gemini_thinking_level = "medium"
        medium = cache_digest(4, "types of angles")
    finally:
        settings.gemini_thinking_level = original

    assert low != medium


def test_cache_identity_includes_tagger_model(monkeypatch):
    original = cache_digest(4, "types of angles")
    monkeypatch.setattr(
        cache_module,
        "TAGGER_CONFIG",
        LLMRoleConfig("tagger", "gemini-different-tagger", 512),
    )
    assert cache_digest(4, "types of angles") != original


def test_cache_identity_includes_refiner_and_tagger_prompts(monkeypatch):
    original = cache_digest(4, "types of angles")
    monkeypatch.setitem(cache_module.PROMPT_VERSIONS, "refiner", "changed")
    assert cache_digest(4, "types of angles") != original

    monkeypatch.setitem(cache_module.PROMPT_VERSIONS, "refiner", "v1")
    original = cache_digest(4, "types of angles")
    monkeypatch.setitem(cache_module.PROMPT_VERSIONS, "tagger", "changed")
    assert cache_digest(4, "types of angles") != original


def test_provider_and_model_ids_must_match():
    with pytest.raises(ValueError, match="does not match"):
        Settings(
            llm_provider="claude",
            generator_model_id="gemini-3.7-flash",
            reviewer_model_id="gemini-3.7-flash",
        )
