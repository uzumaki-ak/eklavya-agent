"""Reviewer Agent — evaluates the Generator's output.

Responsibility: judge age appropriateness, conceptual correctness, clarity,
topic coverage, and question quality.
Structured input: the Generator's content JSON. Structured output: ReviewerOutput.

Note on grade and topic: the spec's Reviewer input contract is content-only, but
neither age appropriateness nor topic coverage can be judged without them. The
formal schema is kept exactly as specified; both are injected as prompt context.

The model answers into ReviewerJudgement, which carries one extra internal field
(`addresses_requested_topic`). That field is enforced in code — an off-topic
lesson cannot pass no matter what verdict the model returns — and is then dropped
when the judgement is projected to the spec's public {status, feedback} shape.
"""

import json
import logging

from app.agents.client import REVIEWER_CONFIG, call_llm
from app.agents.prompts import REVIEWER_SYSTEM, REVIEWER_USER, grade_band_guidance
from app.schemas.content import GeneratorOutput, ReviewerJudgement, ReviewerOutput

logger = logging.getLogger(__name__)


class ReviewerAgent:
    async def run(
        self,
        content: GeneratorOutput,
        grade: int,
        topic: str,
        deadline: float,
        counters: dict | None = None,
    ) -> ReviewerOutput:
        system = REVIEWER_SYSTEM.format(band=grade_band_guidance(grade))
        user = REVIEWER_USER.format(
            grade=grade,
            topic=topic,
            content=json.dumps(content.model_dump(), indent=2, ensure_ascii=False),
        )

        judgement = await call_llm(
            config=REVIEWER_CONFIG,
            system=system,
            user=user,
            output_format=ReviewerJudgement,
            deadline=deadline,
            counters=counters,
        )

        if not judgement.addresses_requested_topic:
            # Worth its own log line: this is the pipeline catching the model
            # approving a lesson on the wrong subject.
            logger.warning("reviewer flagged topic drift for %r", topic[:60])

        logger.info(
            "reviewer verdict=%s on_topic=%s feedback_items=%d",
            judgement.status,
            judgement.addresses_requested_topic,
            len(judgement.feedback),
        )
        return judgement.to_output()
