"""Content safety checks.

Independent of, and underneath, the Reviewer agent's own judgement — the audience
is children, so content passes two unrelated gates rather than one.

A *block* and a *check failure* are deliberately different exceptions: both fail
closed, but only one means "we actually caught something".
"""

import logging
import re

from app.core.config import settings
from app.core.exceptions import ModerationBlocked, ModerationUnavailable
from app.schemas.content import GeneratorOutput

logger = logging.getLogger(__name__)

# Fast local pre-filter for obviously off-limits topics. This is a floor, not a
# ceiling — it catches blatant cases cheaply before any LLM call is made.
_BLOCKED_PATTERNS = [
    r"\b(porn|sex|nude|erotic)\w*",
    r"\b(suicide|self.?harm|kill yourself)\b",
    r"\b(cocaine|heroin|meth|weed|drugs?)\b",
    r"\b(bomb|explosive|firearm|weapon)\s*(making|building|how to)",
    r"\b(gore|torture|mutilat)\w*",
]
_BLOCKED_RE = re.compile("|".join(_BLOCKED_PATTERNS), re.IGNORECASE)


def _clear(stage: str) -> dict:
    return {"outcome": "clear", "policy_version": settings.moderation_policy_version, "stage": stage}


async def moderate_topic(topic: str) -> dict:
    """Check the user-supplied topic before generation starts."""
    try:
        if _BLOCKED_RE.search(topic):
            logger.warning("topic blocked by moderation: %r", topic[:80])
            raise ModerationBlocked(topic)
        return _clear("topic")
    except ModerationBlocked:
        raise
    except Exception as exc:  # the check itself broke — fail closed, distinctly
        logger.exception("moderation check unavailable")
        raise ModerationUnavailable() from exc


async def moderate_content(output: GeneratorOutput) -> dict:
    """Check generated content before it can reach a child's screen."""
    try:
        blob = output.explanation + " " + " ".join(
            q.question + " " + " ".join(q.options) for q in output.mcqs
        )
        if _BLOCKED_RE.search(blob):
            logger.warning("generated content blocked by moderation")
            raise ModerationBlocked("generated content")
        return _clear("content")
    except ModerationBlocked:
        raise
    except Exception as exc:
        logger.exception("moderation check unavailable")
        raise ModerationUnavailable() from exc
