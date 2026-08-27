"""Moderation must fail in the right direction.

The original filter matched bare nouns ("sex", "drugs") and required the verb
after the noun for weapons ("bomb making"), so it blocked ordinary curriculum
topics while letting "how to make a bomb at home" straight through. These cases
pin both directions.
"""

import pytest

from app.core.exceptions import ModerationBlocked
from app.services.moderation import moderate_content, moderate_topic
from app.schemas.content import GeneratorOutput, MCQ

# Real topics from a school syllabus. Blocking any of these makes the product
# unusable for the audience it exists to serve.
ALLOWED_TOPICS = [
    "sexual reproduction in plants",
    "why drugs are harmful to the body",
    "sexism in the workplace",
    "the human reproductive system",
    "how vaccines protect us from disease",
    "World War II and the atomic bomb",
    "the history of nuclear weapons",
    "alcohol and its effects on the liver",
    "how the heart pumps blood",
    "types of angles",
]

# Requests for instructions to cause harm. Phrased the way someone would
# actually type them, not in the noun-then-verb order the old pattern expected.
BLOCKED_TOPICS = [
    "how to make a bomb at home",
    "ways to hurt yourself",
    "how to make a weapon",
    "how to kill myself",
    "steps to build an explosive",
    "how to hurt someone badly",
    "where to buy cocaine",
    "how to get drugs without being caught",
]


@pytest.mark.parametrize("topic", ALLOWED_TOPICS)
async def test_curriculum_topics_are_allowed(topic):
    result = await moderate_topic(topic)
    assert result["outcome"] == "clear"


@pytest.mark.parametrize("topic", BLOCKED_TOPICS)
async def test_harmful_requests_are_blocked(topic):
    with pytest.raises(ModerationBlocked):
        await moderate_topic(topic)


async def test_generated_content_is_screened_too():
    """The output gate runs on the same rules as the input gate."""
    harmful = GeneratorOutput(
        explanation="Here is how to make a bomb at home using household items.",
        mcqs=[
            MCQ(
                question="What do you need?",
                options=["Wire", "Clock", "Powder", "Tape"],
                answer="Wire",
            )
        ],
    )
    with pytest.raises(ModerationBlocked):
        await moderate_content(harmful)


async def test_ordinary_content_passes_the_output_gate():
    benign = GeneratorOutput(
        explanation="A right angle measures exactly 90 degrees.",
        mcqs=[
            MCQ(
                question="How many degrees is a right angle?",
                options=["45", "90", "180", "360"],
                answer="90",
            )
        ],
    )
    assert (await moderate_content(benign))["outcome"] == "clear"
