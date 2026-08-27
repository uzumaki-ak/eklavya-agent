"""Content safety pre-filter.

Runs independently of, and underneath, the Reviewer agent's own judgement — the
audience is children, so content passes two unrelated gates rather than one.

A *block* and a *check failure* are deliberately different exceptions: both fail
closed, but only one means "we actually caught something".

DESIGN NOTE — why this matches intent, not nouns.
The first version of this filter matched bare words ("sex", "drugs", "bomb").
That is the wrong shape for an education product: it blocked "sexual reproduction
in plants", "why drugs are harmful to the body" and "sexism in the workplace"
while happily allowing "how to make a bomb at home", because its weapons rule
expected the noun before the verb. A child asking a legitimate biology question
was refused; a child asking for bomb instructions was served.

So the rule here is: a topic is blocked when it pairs an *instruction- or
acquisition-seeking intent* with a *harmful object*, or when it matches a small
set of phrases that are harmful regardless of framing. Nouns alone never block.

SCOPE — this is a demo-grade pre-filter, not production child safety. It is
high-precision by design (it would rather miss an obfuscated request than block
a science lesson) and it cannot reason about context the way a hosted classifier
can. Before real children use this, replace it with a proper moderation service.
"""

import logging
import re

from app.core.config import settings
from app.core.exceptions import ModerationBlocked, ModerationUnavailable
from app.schemas.content import GeneratorOutput

logger = logging.getLogger(__name__)

# "Tell me how to do X" / "where do I get X" — the framing that turns a topic
# into a request for capability.
_INTENT = r"(?:how\s+(?:to|do\s+i|can\s+i)|ways?\s+to|steps?\s+to|guide\s+to|" \
          r"instructions?\s+for|teach\s+me\s+to|where\s+(?:to|can\s+i)\s+(?:buy|get|find)|" \
          r"best\s+way\s+to)"

# Things nobody should be walked through making, using or acquiring.
_HARM_OBJECT = r"(?:bomb|explosive|grenade|weapon|gun|firearm|ammunition|poison|" \
               r"cocaine|heroin|meth(?:amphetamine)?|fentanyl|illegal\s+drugs?|drugs?)"

_BLOCKED_PATTERNS = [
    # Instruction- or acquisition-seeking + a harmful object, in either order.
    rf"{_INTENT}\b[^.?!]{{0,40}}?\b(?:make|build|create|construct|assemble|obtain|buy|get|use|hide)\b"
    rf"[^.?!]{{0,30}}?\b{_HARM_OBJECT}\b",
    rf"{_INTENT}\b[^.?!]{{0,30}}?\b{_HARM_OBJECT}\b",

    # Self-harm and suicide, help-seeking excluded below.
    r"\b(?:kill|hurt|harm|injure|cut)\s+(?:my|your|him|her|them)self\b",
    r"\b(?:how|ways?|methods?|easiest\s+way)\b[^.?!]{0,30}?\b(?:kill\s+myself|end\s+my\s+life|"
    r"commit\s+suicide|take\s+my\s+own\s+life)\b",
    r"\bsuicide\s+(?:method|technique|instruction|note)s?\b",

    # Violence directed at other people.
    r"\bhow\s+to\s+(?:hurt|kill|attack|stab|shoot|poison)\s+"
    r"(?:someone|somebody|people|a\s+person|him|her|them)\b",
    r"\bhurt\s+(?:someone|somebody|people)\s+(?:badly|seriously)\b",

    # Sexually explicit material. Deliberately does NOT match "sex" or "sexual",
    # so reproduction, puberty and health topics remain teachable.
    r"\b(?:porn|pornography|pornographic|nudes?|nude\s+(?:photo|pic|image)s?|erotica?|"
    r"sexting|explicit\s+sexual\s+content)\b",

    # Graphic violence as instruction or entertainment, not as history.
    r"\bhow\s+to\s+(?:torture|mutilate|dismember)\b",
    r"\b(?:torture|mutilation)\s+(?:porn|video|method|technique)s?\b",
]
_BLOCKED_RE = re.compile("|".join(_BLOCKED_PATTERNS), re.IGNORECASE)

# Asking for help is not the same as asking for a method. These win over the
# self-harm rules above so a child reaching out is never met with a refusal.
_HELP_SEEKING = re.compile(
    r"\b(?:help|support|prevent|prevention|warning\s+signs?|talk\s+to|helpline|"
    r"hotline|counsell?or|coping|recover(?:y|ing)?)\b",
    re.IGNORECASE,
)


def _clear(stage: str) -> dict:
    return {"outcome": "clear", "policy_version": settings.moderation_policy_version, "stage": stage}


def _is_blocked(text: str) -> bool:
    if not _BLOCKED_RE.search(text):
        return False
    # A match that also reads as help-seeking ("how to help someone who self-harms")
    # is educational, not a request for method.
    return not _HELP_SEEKING.search(text)


async def moderate_topic(topic: str) -> dict:
    """Check the user-supplied topic before generation starts."""
    try:
        if _is_blocked(topic):
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
        if _is_blocked(blob):
            logger.warning("generated content blocked by moderation")
            raise ModerationBlocked("generated content")
        return _clear("content")
    except ModerationBlocked:
        raise
    except Exception as exc:
        logger.exception("moderation check unavailable")
        raise ModerationUnavailable() from exc
