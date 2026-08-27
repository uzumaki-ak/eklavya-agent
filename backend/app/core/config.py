"""Application settings, loaded from environment / .env."""

from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Model provider ---
    # "claude" or "gemini". Gemini has a genuinely free tier; Claude needs credits.
    llm_provider: Literal["claude", "gemini"] = "gemini"
    anthropic_api_key: str = ""  # falls back to SDK's own env/profile resolution when blank
    gemini_api_key: str = ""
    generator_model_id: str = "gemini-3.7-flash"
    reviewer_model_id: str = "gemini-3.7-flash"
    gemini_thinking_level: Literal["low", "medium", "high"] = "low"

    # --- Infrastructure ---
    database_url: str = "postgresql+asyncpg://eklavya:eklavya@postgres:5432/eklavya"
    redis_url: str = "redis://redis:6379/0"

    # --- Concurrency / deadlines (see ARCHITECTURE.md "Concurrency & resilience") ---
    llm_max_concurrency: int = 4  # in-flight LLM calls; tune from observed 429 rate
    # Process-local safety cap. Check the active project/model quota in AI Studio.
    # Set 0 to disable; when non-zero, keep a single worker process.
    llm_requests_per_minute: int = 14
    llm_call_timeout_seconds: float = 40.0
    pipeline_deadline_seconds: float = 120.0  # hard budget for one whole job
    saq_job_timeout_seconds: int = 150  # queue-level safety net above the pipeline deadline
    transport_max_attempts: int = 2  # fail visibly instead of retrying for minutes
    schema_repair_max_attempts: int = 2  # extra tries when output fails Pydantic validation

    # --- Leasing (see ARCHITECTURE.md "Idempotency & job leasing") ---
    job_lease_seconds: int = 120
    job_lease_renew_seconds: float = 35.0
    flight_lease_seconds: int = 45
    flight_lease_renew_seconds: float = 15.0

    # --- Cache identity versions; bump any of these to invalidate cached content ---
    # v4: Reviewer feedback is required in the provider's structured schema.
    # v5: MCQ options are reordered in code — pre-v5 cached lessons still carry
    # the model's answer-first bias, so they must not keep being served.
    schema_version: str = "v5"
    canonicalizer_version: str = "v1"
    # v3: direct action/object grammar replaces the brittle proximity matcher.
    # Bumping this invalidates cached content approved under the old rules —
    # without it, lessons cleared by the broken filter would keep being served.
    moderation_policy_version: str = "v3"

    @model_validator(mode="after")
    def model_ids_match_provider(self):
        """Fail at startup instead of sending one vendor another vendor's ID."""
        expected_prefix = "gemini-" if self.llm_provider == "gemini" else "claude-"
        for field_name in ("generator_model_id", "reviewer_model_id"):
            model_id = getattr(self, field_name)
            if not model_id.startswith(expected_prefix):
                raise ValueError(
                    f"{field_name.upper()}={model_id!r} does not match "
                    f"LLM_PROVIDER={self.llm_provider!r}"
                )
        return self

    @field_validator("database_url", "redis_url", mode="before")
    @classmethod
    def clean_url(cls, value: str) -> str:
        """Strip whitespace and stray quotes.

        Values pasted into a hosting dashboard routinely pick up a trailing
        newline or wrapping quotes, which produce a confusing parse failure far
        from the cause.
        """
        if not isinstance(value, str):
            return value
        return value.strip().strip('"').strip("'")

    @field_validator("database_url")
    @classmethod
    def force_async_driver(cls, value: str) -> str:
        """Managed providers (Railway, Neon, Heroku) hand out sync-driver URLs.

        We use an async engine, so normalize the scheme rather than requiring the
        URL to be hand-edited — getting this wrong fails only at first connect.
        """
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value[len(prefix):]
        if not value.startswith("postgresql+asyncpg://"):
            # Fail loudly here rather than as an opaque SQLAlchemy parse error.
            raise ValueError(
                f"DATABASE_URL must start with postgresql:// or postgres://; "
                f"got {value[:20]!r}... (length {len(value)})"
            )
        return value


settings = Settings()
