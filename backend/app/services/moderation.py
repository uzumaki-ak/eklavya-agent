"""Content safety pre-filter.

Runs independently of, and underneath, the Reviewer agent's own judgement — the
audience is children, so content passes two unrelated gates rather than one.

A *block* and a *check failure* are deliberately different exceptions: both fail
closed, but only one means "we actually caught something".

DESIGN: match harmful capability-seeking structure, not bare nouns. Direct
action/object grammar keeps curriculum topics such as the history of weapons
teachable, while separate patterns cover passive instructions, violence,
self-harm, and explicit sexual material.

SCOPE — this is a demo-grade pre-filter, not production child safety. It reasons
about word proximity, not meaning, so euphemistic harm may pass and unusual
legitimate phrasing may be blocked. Use a hosted classifier for a real product.
"""

import logging
import re

from app.core.config import settings
from app.core.exceptions import ModerationBlocked, ModerationUnavailable
from app.schemas.content import GeneratorOutput
from app.services.moderation_targets import PROTECTED_TARGET_PATTERN

logger = logging.getLogger(__name__)

# Direct actions are matched against the object they actually act on, keeping
# "create a report about a bomb" distinct from "create a bomb".
_ACTION = (
    r"(?:make|making|build|building|construct|constructing|assemble|assembling|"
    r"create|creating|manufacture|manufacturing|synthesi[sz]e|synthesi[sz]ing|"
    r"produce|producing|cook|cooking|obtain|obtaining|acquire|acquiring|buy|buying|"
    r"purchase|purchasing|sell|selling|order|ordering|smuggle|smuggling|steal|"
    r"stealing|get|getting|use|using)"
)

# Only harmless glue may sit between action and object; arbitrary words would
# make "create a school report about a bomb" unsafe by accident.
_GLUE = (
    r"\s+(?:(?:me|us)\s+)?(?:(?:a|an|the|some|my|your)\s+)?"
    r"(?:(?:homemade|working|real|illegal|powerful)\s+){0,2}"
)
_NEAR = r"[^.?!\n]{0,40}"

# Things nobody should be walked through producing or acquiring.
_WEAPON = r"(?:bombs?|explosives?|grenades?|landmines?|weapons?|guns?|rifles?|firearms?|ammunition|poison)"
_HARD_DRUG = r"(?:cocaine|heroin|meth(?:amphetamine)?|fentanyl|ecstasy|lsd)"

# "drugs" alone is a school topic ("why drugs are harmful", "prescription drugs
# for asthma"), so it only counts as an object in an illicit-trade context.
_ILLICIT_DRUG = r"(?:illegal\s+drugs?|drugs?\s+illegally|street\s+drugs?)"

_OBJECT = rf"(?:{_WEAPON}|{_HARD_DRUG}|{_ILLICIT_DRUG})"

# Match a person seeking drugs (or a direct imperative), not the bare verb
# "find" in a legitimate police or customs lesson.
_DRUG_OBJECT = rf"(?:{_HARD_DRUG}|{_ILLICIT_DRUG}|drugs?)"
_SEEKING_DRUGS = (
    rf"(?:\b(?:where|how)\s+(?:can|could|do|should|would)\s+(?:i|we|you)\s+find\b"
    rf"|\b(?:how|where|ways?)\s+to\s+find\b|\bhelp\s+me\s+find\b|^\s*find\b)"
    rf"{_NEAR}\b{_DRUG_OBJECT}\b"
)

# Passive capability questions need their own grammar: "how are bombs made"
# contains no active action-before-object phrase.
_PASSIVE_ACTION = (
    r"(?:made|built|constructed|assembled|created|manufactured|produced|"
    r"synthesi[sz]ed|cooked|obtained|acquired|bought|purchased|used)"
)

# Concealment. Health education never needs to avoid being caught.
_EVASION = (
    r"(?:without\s+(?:being|getting)\s+caught|without\s+(?:anyone|my\s+parents|"
    r"my\s+mum|my\s+mom|my\s+dad|teachers?)\s+(?:knowing|finding\s+out)|"
    r"secretly|from\s+a\s+dealer|on\s+the\s+black\s+market)"
)

# Enumerate protected people/animals; legitimate science objects are unbounded.
_PROTECTED_TARGET = PROTECTED_TARGET_PATTERN
_TARGET_OWNER = r"(?:my|your|his|her|our|their|a|an|the|this|that|another)"

_BLOCKED_PATTERNS = [
    # Direct action on a harmful object, including short imperatives such as
    # "find cocaine" and "produce a bomb".
    rf"\b{_ACTION}\b{_GLUE}\b{_OBJECT}\b",

    # Object-first noun phrases: "bomb making", "cocaine buying".
    rf"\b{_OBJECT}\b\s+{_ACTION}\b",

    # Passive instructional questions: "how are bombs made?" and
    # "how is cocaine produced?".
    rf"\bhow\b{_NEAR}\b{_OBJECT}\b{_NEAR}\b{_PASSIVE_ACTION}\b",
    rf"\bhow\b{_NEAR}\b{_PASSIVE_ACTION}\b{_NEAR}\b{_OBJECT}\b",

    # Instructions for the object, without an explicit verb between them.
    rf"\b(?:instructions?|recipe|blueprint|tutorial|guide)\b{_NEAR}\b{_OBJECT}\b",
    rf"\b{_OBJECT}\b{_NEAR}\b(?:instructions?|recipe|blueprint|tutorial)\b",

    # Drug-seeking "find" requests, without catching descriptions such as
    # "how customs officers find illegal drugs".
    _SEEKING_DRUGS,

    # Generic "drugs" is a school topic, but concealment language settles the
    # intent: "how to get drugs without being caught" is not health education.
    rf"\bdrugs?\b{_NEAR}\b{_EVASION}\b",
    rf"\b{_EVASION}\b{_NEAR}\bdrugs?\b",

    # Self-harm and suicide. The help-seeking override below applies to THIS
    # group only — it must never excuse a weapons or violence request.
    r"\b(?:kill|hurt|harm|injure|cut)\s+(?:my|your|him|her|them)self\b",
    r"\b(?:kill\s+myself|end\s+my\s+life|commit\s+suicide|take\s+my\s+own\s+life)\b",
    r"\bsuicide\s+(?:method|technique|instruction|note)s?\b",

    # Closed person/animal targets keep science and PE objects teachable.
    r"\b(?:(?:how|ways?|steps?)\b[^.?!\n]{0,20}?\bto\s+)?"
    r"(?:hurt|kill|attack|stab|shoot|poison)\s+"
    r"(?:someone|somebody|people|a\s+person|him|her|them|"
    rf"(?:other\s+)?{_PROTECTED_TARGET}|"
    rf"{_TARGET_OWNER}\s+(?:[a-z][a-z'-]*\s+){{0,2}}(?:other\s+)?"
    rf"{_PROTECTED_TARGET})\b",
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

# Scope pastoral phrasing to self-harm; a global override once let a weapons
# request through merely because it contained "support".
_SELF_HARM_RE = re.compile(
    r"\b(?:kill|hurt|harm|injure|cut)\s+(?:my|your|him|her|them)self\b|"
    r"\b(?:kill\s+myself|end\s+my\s+life|commit\s+suicide|take\s+my\s+own\s+life)\b",
    re.IGNORECASE,
)
_HELP_SEEKING = re.compile(
    r"\b(?:help(?:ing)?|support(?:ing)?|prevent(?:ion|ing)?|warning\s+signs?|"
    r"talk(?:ing)?\s+to|helpline|hotline|counsell?or|coping|recover(?:y|ing)?|"
    r"someone\s+who)\b",
    re.IGNORECASE,
)


def _clear(stage: str) -> dict:
    return {"outcome": "clear", "policy_version": settings.moderation_policy_version, "stage": stage}


def _is_blocked(text: str) -> bool:
    match = _BLOCKED_RE.search(text)
    if not match:
        return False
    # "How to help someone who self-harms" is educational. That leniency applies
    # only when the sole reason for the match was self-harm wording.
    only_self_harm = _SELF_HARM_RE.search(text) and not _BLOCKED_RE.search(
        _SELF_HARM_RE.sub(" ", text)
    )
    return not (only_self_harm and _HELP_SEEKING.search(text))


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
    """Check generated content before it can reach a child's screen.

    The text comes from the schema itself: assembling it here would have let
    Part 2's new `teacher_notes` bypass the filter, a gap that fails silently.
    """
    try:
        if _is_blocked(output.moderation_blob()):
            logger.warning("generated content blocked by moderation")
            raise ModerationBlocked("generated content")
        return _clear("content")
    except ModerationBlocked:
        raise
    except Exception as exc:
        logger.exception("moderation check unavailable")
        raise ModerationUnavailable() from exc
