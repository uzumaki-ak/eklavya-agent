"""Provider selection.

LLM_PROVIDER decides the vendor. Imports are lazy so an unused provider is not
initialized and does not require credentials at runtime.
"""

from functools import lru_cache

from app.agents.providers.base import LLMProvider, LLMRoleConfig
from app.core.config import settings

__all__ = [
    "LLMProvider",
    "LLMRoleConfig",
    "get_provider",
    "GENERATOR_CONFIG",
    "REFINER_CONFIG",
    "REVIEWER_CONFIG",
    "TAGGER_CONFIG",
]


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
# The Refiner returns a whole rewritten artifact, so it needs the Generator's
# budget, not the Reviewer's. It shares the Generator's model deliberately: the
# roles differ by prompt and by what they are given, not by capability.
REFINER_CONFIG = LLMRoleConfig("refiner", settings.generator_model_id, 4096)
REVIEWER_CONFIG = LLMRoleConfig("reviewer", settings.reviewer_model_id, 2048)
# Tagging is a short classification into closed sets.
TAGGER_CONFIG = LLMRoleConfig("tagger", settings.tagger_model_id, 512)
