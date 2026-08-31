"""Refiner Agent — rewrites a rejected draft against the Reviewer's feedback.

Responsibility: fix the specific problems named in a review, without discarding
the parts that were not criticised.
Structured input: the previous GeneratorOutput plus a list of ReviewFeedback.
Structured output: GeneratorOutput — the same contract as the Generator, because
the pipeline must be able to review a refinement exactly as it reviewed a draft.

Why this is its own agent rather than the Generator with extra text: the two have
different inputs, different instructions, and different failure modes. Part 1 ran
refinement through the Generator, and its most common failure was rewriting the
whole lesson from scratch and losing what the Reviewer had already accepted.
"""

import json
import logging

from app.agents.client import REFINER_CONFIG
from app.agents.contract import check_generated_matches_request
from app.agents.execution import ExecutionContext, call_with_repair
from app.agents.option_order import balanced_output
from app.agents.prompts import (
    REFINER_SYSTEM,
    REFINER_USER,
    escape_topic,
    grade_band_guidance,
)
from app.schemas.content import GeneratorInput, GeneratorOutput
from app.schemas.review import ReviewFeedback

logger = logging.getLogger(__name__)

_REPAIR_HINT = (
    " Remember that correct_index is 0-based and must point at the one correct "
    "option, and that explanation.grade must equal the requested grade."
)


def _render_feedback(feedback: list[ReviewFeedback]) -> str:
    """Field-anchored, one per line — the form the Refiner is told to expect."""
    if not feedback:
        return "- (no specific items were recorded; improve overall quality)"
    return "\n".join(f"- {item.field}: {item.issue}" for item in feedback)


class RefinerAgent:
    """Input: (GeneratorInput, previous draft, feedback). Output: GeneratorOutput."""

    async def run(
        self,
        data: GeneratorInput,
        draft: GeneratorOutput,
        feedback: list[ReviewFeedback],
        ctx: ExecutionContext,
    ) -> GeneratorOutput:
        system = REFINER_SYSTEM.format(band=grade_band_guidance(data.grade))
        user = REFINER_USER.format(
            grade=data.grade,
            topic=escape_topic(data.topic),
            draft=json.dumps(draft.model_dump(), indent=2, ensure_ascii=False),
            feedback=_render_feedback(feedback),
        )

        logger.info("refining draft against %d feedback item(s)", len(feedback))
        output = await call_with_repair(
            role="refiner",
            config=REFINER_CONFIG,
            system=system,
            user=user,
            output_format=GeneratorOutput,
            ctx=ctx,
            validate=lambda revised: check_generated_matches_request(revised, data),
            repair_hint=_REPAIR_HINT,
        )
        return balanced_output(output)
