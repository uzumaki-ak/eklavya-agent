"""Reviewer Agent — evaluates the Generator's output.

Responsibility: judge age appropriateness, conceptual correctness, and clarity.
Structured input: the Generator's content JSON. Structured output: ReviewerOutput.

Note on grade: the spec's Reviewer input contract is content-only, but age
appropriateness can't be judged without knowing the target grade. The formal
schema is kept exactly as specified; grade is injected as prompt context.
"""

import json
import logging

from app.agents.client import REVIEWER_CONFIG, call_llm
from app.agents.prompts import REVIEWER_SYSTEM, REVIEWER_USER, grade_band_guidance
from app.schemas.content import GeneratorOutput, ReviewerOutput

logger = logging.getLogger(__name__)


class ReviewerAgent:
    async def run(
        self,
        content: GeneratorOutput,
        grade: int,
        deadline: float,
        counters: dict | None = None,
    ) -> ReviewerOutput:
        system = REVIEWER_SYSTEM.format(band=grade_band_guidance(grade))
        user = REVIEWER_USER.format(
            grade=grade,
            content=json.dumps(content.model_dump(), indent=2, ensure_ascii=False),
        )

        review = await call_llm(
            config=REVIEWER_CONFIG,
            system=system,
            user=user,
            output_format=ReviewerOutput,
            deadline=deadline,
            counters=counters,
        )

        logger.info("reviewer verdict=%s feedback_items=%d", review.status, len(review.feedback))
        return review
