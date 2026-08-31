"""Reviewer Agent — the quantitative gatekeeper.

Responsibility: score the draft 1-5 on age appropriateness, correctness, clarity
and coverage, and attach field-anchored feedback for every problem found.
Structured input: the Generator's content. Structured output: ReviewerOutput.

Note on grade and topic: the spec's Reviewer input contract is content-only, but
neither age appropriateness nor coverage can be judged without them. The formal
schema stays exactly as specified; both are injected as prompt context.

The verdict is not the model's to make. It answers into ReviewerJudgement, which
carries its self-reported `pass` and an internal `addresses_requested_topic`
flag; `ReviewerJudgement.passed` then derives the real verdict from the scores
and the outstanding feedback. See `app.schemas.review` for the thresholds.
"""

import json
import logging

from app.agents.client import REVIEWER_CONFIG
from app.agents.contract import check_review_paths_exist
from app.agents.execution import ExecutionContext, call_with_repair
from app.agents.prompts import (
    REVIEWER_SYSTEM,
    REVIEWER_USER,
    escape_topic,
    grade_band_guidance,
)
from app.schemas.content import GeneratorOutput
from app.schemas.review import ReviewerJudgement, ReviewerOutput

logger = logging.getLogger(__name__)

_REPAIR_HINT = (
    " Include scores for all four dimensions, pass, feedback, and "
    "addresses_requested_topic. Every feedback item needs a real field path."
)


class ReviewerAgent:
    """Input: GeneratorOutput (+ grade, topic). Output: ReviewerOutput."""

    async def run(
        self,
        content: GeneratorOutput,
        grade: int,
        topic: str,
        ctx: ExecutionContext,
    ) -> ReviewerOutput:
        """The spec-shaped call: content in, {scores, pass, feedback} out."""
        return (await self.judge(content, grade, topic, ctx)).to_output()

    async def judge(
        self,
        content: GeneratorOutput,
        grade: int,
        topic: str,
        ctx: ExecutionContext,
    ) -> ReviewerJudgement:
        """The full judgement, including the internal topic-coverage flag.

        Exposed separately so the evaluation harness can score topic-drift
        detection, which the public shape deliberately hides.
        """
        system = REVIEWER_SYSTEM.format(band=grade_band_guidance(grade))
        user = REVIEWER_USER.format(
            grade=grade,
            topic=escape_topic(topic),
            content=json.dumps(content.model_dump(), indent=2, ensure_ascii=False),
        )

        judgement = await call_with_repair(
            role="reviewer",
            config=REVIEWER_CONFIG,
            system=system,
            user=user,
            output_format=ReviewerJudgement,
            ctx=ctx,
            validate=lambda result: check_review_paths_exist(result, content),
            repair_hint=_REPAIR_HINT,
        )

        if not judgement.addresses_requested_topic:
            # Worth its own log line: this is the pipeline catching the model
            # approving a lesson on the wrong subject.
            logger.warning("reviewer flagged topic drift for %r", topic[:60])
        if judgement.overruled:
            # The gap between what the model claimed and what its own scores
            # support. Frequent overrules mean the thresholds need recalibrating,
            # not that the enforcement is wrong.
            logger.warning(
                "reviewer reported pass=%s but the scores enforce pass=%s",
                judgement.reported_pass,
                judgement.passed,
            )

        logger.info(
            "reviewer verdict=%s scores=%s on_topic=%s feedback_items=%d",
            "pass" if judgement.passed else "fail",
            judgement.scores.model_dump(),
            judgement.addresses_requested_topic,
            len(judgement.feedback),
        )
        return judgement
