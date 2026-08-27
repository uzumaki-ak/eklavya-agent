"""Result cache — exact-match on a versioned identity hash.

Three rules that matter:
  - The key includes every input that could change the output (both models, both
    prompt versions, schema/canonicalizer/policy versions). Change any of them and
    old entries stop being served instead of silently going stale.
  - The stored value is the FULL pipeline envelope, not just the final answer —
    the UI must still show all three stages on a cache hit.
  - The stored value carries its own status, so a cached *failing* review is
    replayed as a fail rather than being reported as a pass.
"""

import hashlib
import json
import logging

import redis.asyncio as redis

from app.agents.providers import GENERATOR_CONFIG, REVIEWER_CONFIG
from app.agents.prompts import PROMPT_VERSIONS
from app.core.config import settings
from app.services.envelope import STAGE_FIELDS, cacheable

logger = logging.getLogger(__name__)

_redis: redis.Redis | None = None
CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def cache_digest(grade: int, canonical_topic: str) -> str:
    """Stable hash of everything that determines the output."""
    identity = {
        "grade": grade,
        "topic": canonical_topic,
        "provider": settings.llm_provider,
        "generator_model": GENERATOR_CONFIG.model_id,
        "generator_max_tokens": GENERATOR_CONFIG.max_tokens,
        "reviewer_model": REVIEWER_CONFIG.model_id,
        "reviewer_max_tokens": REVIEWER_CONFIG.max_tokens,
        "generator_prompt_version": PROMPT_VERSIONS["generator"],
        "reviewer_prompt_version": PROMPT_VERSIONS["reviewer"],
        "schema_version": settings.schema_version,
        "canonicalizer_version": settings.canonicalizer_version,
        "moderation_policy_version": settings.moderation_policy_version,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def _key(digest: str) -> str:
    return f"cache:v5:{digest}"


async def get_cached(digest: str) -> tuple[dict, str] | None:
    """Returns (envelope, status) or None. Status is stored, never re-guessed."""
    try:
        raw = await get_redis().get(_key(digest))
    except Exception:
        logger.exception("cache read failed; treating as a miss")
        return None
    if raw is None:
        return None

    try:
        payload = json.loads(raw)
        envelope = {field: payload.get(field) for field in STAGE_FIELDS}
        status = payload["status"]
    except (json.JSONDecodeError, KeyError):
        logger.warning("corrupt cache entry, ignoring: %s", digest[:12])
        return None

    if not cacheable(status):  # defensive: never replay an error as a result
        return None
    return envelope, status


async def set_cached(digest: str, envelope: dict, status: str) -> None:
    """Only clean, completed results are cacheable.

    Never cache an error or a moderation block — a transient failure would
    otherwise be served to everyone asking for that topic for 30 days.
    """
    if not cacheable(status):
        return
    try:
        await get_redis().set(
            _key(digest), json.dumps({**envelope, "status": status}), ex=CACHE_TTL_SECONDS
        )
    except Exception:
        # A cache write failure must never fail the job — the result is already durable.
        logger.exception("cache write failed for %s", digest[:12])
