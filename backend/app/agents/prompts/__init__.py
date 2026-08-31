"""Prompt templates and their versions, one module per agent role.

Versions are part of the cache identity — bump one and cached content built with
the old prompt stops being served.
"""

from app.agents.prompts.generator import GENERATOR_SYSTEM, GENERATOR_USER
from app.agents.prompts.refiner import REFINER_SYSTEM, REFINER_USER
from app.agents.prompts.reviewer import REVIEWER_SYSTEM, REVIEWER_USER
from app.agents.prompts.tagger import TAGGER_SYSTEM, TAGGER_USER

__all__ = [
    "PROMPT_VERSIONS",
    "escape_topic",
    "grade_band_guidance",
    "GENERATOR_SYSTEM",
    "GENERATOR_USER",
    "REFINER_SYSTEM",
    "REFINER_USER",
    "REVIEWER_SYSTEM",
    "REVIEWER_USER",
    "TAGGER_SYSTEM",
    "TAGGER_USER",
]

# v7 generator: nested explanation, correct_index, teacher_notes.
# v6 reviewer: 1-5 scores and field-referenced feedback.
PROMPT_VERSIONS = {
    "generator": "v7",
    "reviewer": "v6",
    "refiner": "v1",
    "tagger": "v1",
}


def escape_topic(topic: str) -> str:
    """Neutralise the delimiter inside untrusted input.

    The topic is user-supplied and goes inside <topic> tags. A topic containing
    "</topic>" would otherwise close the tag early and let whatever follows read
    as prompt text rather than as the subject to teach.
    """
    return topic.replace("<", "‹").replace(">", "›")


# Rough vocabulary/sentence guidance per grade band. Kept explicit rather than
# left to the model's judgement, since "age appropriate" is the thing being graded.
_GRADE_BANDS = {
    (1, 2): "very simple words, sentences under 10 words, concrete everyday examples only",
    (3, 5): "simple words, sentences under 15 words, familiar examples (toys, food, sports)",
    (6, 8): "moderate vocabulary, sentences under 20 words, may introduce one technical term if defined",
    (9, 12): "subject vocabulary is fine, longer sentences allowed, abstract reasoning is fine",
}


def grade_band_guidance(grade: int) -> str:
    for (low, high), guidance in _GRADE_BANDS.items():
        if low <= grade <= high:
            return guidance
    return _GRADE_BANDS[(6, 8)]
