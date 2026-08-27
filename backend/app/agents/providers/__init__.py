"""Provider selection.

LLM_PROVIDER decides the vendor. Imports are lazy so an unused provider is not
initialized and does not require credentials at runtime.
"""

from functools import lru_cache

from app.agents.providers.base import LLMProvider, LLMRoleConfig
from app.core.config import settings

__all__ = ["LLMProvider", "LLMRoleConfig", "get_provider", "GENERATOR_CONFIG", "REVIEWER_CONFIG"]


@lru_cache(maxsize=1)
def get_provider() -> LLMProvider:
    if settings.llm_provider == "gemini":
        from app.agents.providers.gemini import GeminiProvider

        return GeminiProvider()

    if settings.llm_provider == "claude":
        from app.agents.providers.claude import ClaudeProvider

        return ClaudeProvider()

    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider!r}")


# Per-role configs. Model ids come from settings so the same code serves both
# vendors. Cache identity also includes the provider name.
GENERATOR_CONFIG = LLMRoleConfig("generator", settings.generator_model_id, 4096)
REVIEWER_CONFIG = LLMRoleConfig("reviewer", settings.reviewer_model_id, 2048)
