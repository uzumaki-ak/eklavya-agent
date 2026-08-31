"""Tagger Agent — classifies approved content.

Responsibility: label an approved lesson for cataloguing.
Structured input: the approved GeneratorOutput. Structured output: ContentTags.

It runs on approved content only, and the pipeline is what guarantees that: the
Tagger node is reachable only from a passing review. Tags on rejected content
would assert that something the gatekeeper turned down is a catalogued Grade 5
Mathematics lesson, which is worse than having no tags at all.
"""

import json
import logging

from app.agents.client import TAGGER_CONFIG
from app.agents.contract import check_tags_match_request
from app.agents.execution import ExecutionContext, call_with_repair
from app.agents.prompts import TAGGER_SYSTEM, TAGGER_USER, escape_topic
from app.schemas.content import GeneratorInput, GeneratorOutput
from app.schemas.tags import ContentTags

logger = logging.getLogger(__name__)

_REPAIR_HINT = (
    " Every field except topic must be one of the listed values, spelled exactly."
)


class TaggerAgent:
    """Input: approved GeneratorOutput (+ the original request). Output: ContentTags."""

    async def run(
        self,
        data: GeneratorInput,
        content: GeneratorOutput,
        ctx: ExecutionContext,
    ) -> ContentTags:
        user = TAGGER_USER.format(
            grade=data.grade,
            topic=escape_topic(data.topic),
            content=json.dumps(content.model_dump(), indent=2, ensure_ascii=False),
        )

        tags = await call_with_repair(
            role="tagger",
            config=TAGGER_CONFIG,
            system=TAGGER_SYSTEM,
            user=user,
            output_format=ContentTags,
            ctx=ctx,
            validate=lambda result: check_tags_match_request(result, data),
            repair_hint=_REPAIR_HINT,
        )

        logger.info(
            "tagged as %s / %s / %s / %s",
            tags.subject,
            tags.topic,
            tags.difficulty,
            tags.blooms_level,
        )
        return tags
